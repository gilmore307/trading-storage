"""Storage-owned scheduled maintenance runner."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lifecycle import apply_retention_plan, plan_retention

DEFAULT_MAINTENANCE_OUTPUT = Path("storage/90_lifecycle/maintenance/storage_maintenance_summary.json")
MODEL_WORKER_STAGE_TYPES = {"model_generation", "model_evaluation", "promotion_review", "maintenance"}
COMPLETE_STATUSES = {"succeeded", "not_applicable"}
FOLD_STATE_GLOB = "model_training_fold_state_*.json"
FOLD_SCOPED_SOURCE_ROOT = Path("storage/01_source_data/fold_scoped")
ORDERED_STORAGE_ROOTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "01_source_data",
        "storage/01_source_data",
        "durable_source",
        "Reusable Layer 1/2 source foundations plus explicitly fold-scoped target/source artifacts.",
    ),
    ("02_control_plane", "storage/02_control_plane", "durable_control", "Manager task state, workflow state, receipts, and control-plane artifacts."),
    ("03_model_artifacts", "storage/03_model_artifacts", "durable_model", "Model training, diagnostics, research, and promotion-adjacent artifacts."),
    ("04_execution_artifacts", "storage/04_execution_artifacts", "durable_execution", "Realtime observation, shadow/live, and execution-side artifacts."),
    ("05_benchmark_datasets", "storage/05_benchmark_datasets", "durable_benchmark", "Frozen benchmark datasets, acquisition plans, and replay inputs."),
    ("06_dashboard_cache", "storage/06_dashboard_cache", "managed_cache", "Dashboard read-model latest/snapshot/schema/index cache."),
    ("90_lifecycle", "storage/90_lifecycle", "lifecycle_control", "Lifecycle plans, indexes, protected sets, receipts, archives, cache, staging, and logs."),
)


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class StorageMaintenanceSummary:
    """Summary receipt for one scheduled storage maintenance pass."""

    contract_type: str
    generated_at_utc: str
    root: str
    local_retention_enabled: bool
    local_retention_apply: bool
    local_retention_summary: dict[str, int]
    storage_root_inventory_summary: dict[str, Any]
    storage_root_inventory: tuple[dict[str, Any], ...]
    manager_root: str | None
    fold_monitor_enabled: bool
    completed_fold_count: int
    completed_fold_ids: tuple[str, ...]
    fold_backup_candidates: tuple[dict[str, Any], ...]
    fold_source_cleanup_candidates: tuple[dict[str, Any], ...]
    fold_source_cleanup_candidate_count: int
    fold_sql_backup_phase_status: str
    fold_source_cleanup_phase_status: str
    deletion_phase_status: str
    provider_calls_performed: bool
    model_activation_performed: bool
    broker_execution_performed: bool
    account_mutation_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at_utc": self.generated_at_utc,
            "root": self.root,
            "local_retention_enabled": self.local_retention_enabled,
            "local_retention_apply": self.local_retention_apply,
            "local_retention_summary": self.local_retention_summary,
            "storage_root_inventory_summary": self.storage_root_inventory_summary,
            "storage_root_inventory": list(self.storage_root_inventory),
            "manager_root": self.manager_root,
            "fold_monitor_enabled": self.fold_monitor_enabled,
            "completed_fold_count": self.completed_fold_count,
            "completed_fold_ids": list(self.completed_fold_ids),
            "fold_backup_candidates": list(self.fold_backup_candidates),
            "fold_source_cleanup_candidates": list(self.fold_source_cleanup_candidates),
            "fold_source_cleanup_candidate_count": self.fold_source_cleanup_candidate_count,
            "fold_sql_backup_phase_status": self.fold_sql_backup_phase_status,
            "fold_source_cleanup_phase_status": self.fold_source_cleanup_phase_status,
            "deletion_phase_status": self.deletion_phase_status,
            "provider_calls_performed": self.provider_calls_performed,
            "model_activation_performed": self.model_activation_performed,
            "broker_execution_performed": self.broker_execution_performed,
            "account_mutation_performed": self.account_mutation_performed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _build_storage_root_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    inventory: list[dict[str, Any]] = []
    for root_id, relative, lifecycle_role, description in ORDERED_STORAGE_ROOTS:
        base = root / relative
        file_count = 0
        directory_count = 0
        byte_count = 0
        if base.exists():
            if base.is_file() and not base.is_symlink():
                file_count = 1
                byte_count = base.stat().st_size
            elif base.is_dir():
                for path in base.rglob("*"):
                    if path.is_symlink():
                        continue
                    if path.is_dir():
                        directory_count += 1
                    elif path.is_file():
                        file_count += 1
                        try:
                            byte_count += path.stat().st_size
                        except OSError:
                            pass
        inventory.append(
            {
                "root_id": root_id,
                "path": relative,
                "exists": base.exists(),
                "lifecycle_role": lifecycle_role,
                "description": description,
                "file_count": file_count,
                "directory_count": directory_count,
                "byte_count": byte_count,
            }
        )
    return tuple(inventory)


def _storage_root_inventory_summary(inventory: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "contract_type": "storage_root_inventory_summary",
        "root_count": len(inventory),
        "existing_root_count": sum(1 for row in inventory if row.get("exists")),
        "total_file_count": sum(int(row.get("file_count") or 0) for row in inventory),
        "total_directory_count": sum(int(row.get("directory_count") or 0) for row in inventory),
        "total_byte_count": sum(int(row.get("byte_count") or 0) for row in inventory),
        "managed_root_ids": [str(row.get("root_id")) for row in inventory],
    }


def _state_months(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    prefix = "model_training_fold_state_"
    if not stem.startswith(prefix):
        return None
    body = stem.removeprefix(prefix)
    parts = body.split("_")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _fold_id(start_month: str, end_month: str) -> str:
    return f"fold_{start_month}_{end_month}"


def _stage_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    stages = payload.get("stages")
    if not isinstance(stages, list):
        return []
    return [dict(stage) for stage in stages if isinstance(stage, Mapping)]


def _is_completed_model_worker_fold(payload: Mapping[str, Any]) -> bool:
    stages = _stage_rows(payload)
    if not stages:
        return False
    model_stages = [stage for stage in stages if str(stage.get("stage_type") or "") in MODEL_WORKER_STAGE_TYPES]
    if not model_stages:
        return False
    layer_stage_types: dict[int, set[str]] = {}
    for stage in model_stages:
        try:
            layer = int(stage.get("layer") or 0)
        except (TypeError, ValueError):
            return False
        if str(stage.get("status") or "") not in COMPLETE_STATUSES:
            return False
        layer_stage_types.setdefault(layer, set()).add(str(stage.get("stage_type") or ""))
    expected_layers = set(range(1, 11))
    return set(layer_stage_types) == expected_layers and all(
        stage_types >= MODEL_WORKER_STAGE_TYPES for stage_types in layer_stage_types.values()
    )


def _backup_candidate(*, fold_id: str, start_month: str, end_month: str, state_path: Path) -> dict[str, Any]:
    output_path = f"storage/sql_backups/folds/{fold_id}/pending/trading_database.dump"
    return {
        "contract_type": "storage_fold_sql_backup_candidate",
        "fold_id": fold_id,
        "start_month": start_month,
        "end_month": end_month,
        "manager_fold_state_path": str(state_path),
        "backup_mode": "logical_pg_dump_custom",
        "output_path": output_path,
        "backup_command_template": [
            "pg_dump",
            "-Fc",
            "--no-owner",
            "--no-acl",
            "--file",
            output_path,
            "$DATABASE_URL",
        ],
        "globals_backup_command_template": [
            "pg_dumpall",
            "--globals-only",
            "--file",
            output_path.removesuffix(".dump") + ".globals.sql",
        ],
        "restore_smoke_required": True,
        "checksum_required": True,
        "source_delete_allowed_before_backup": False,
    }


def _fold_source_cleanup_candidate(*, fold_id: str, source_folder: Path, root: Path) -> dict[str, Any]:
    relative = source_folder.relative_to(root).as_posix()
    file_count = 0
    byte_count = 0
    for path in source_folder.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        file_count += 1
        try:
            byte_count += path.stat().st_size
        except OSError:
            pass
    return {
        "contract_type": "storage_fold_source_cleanup_candidate",
        "fold_id": fold_id,
        "source_folder_path": relative,
        "cleanup_unit": "fold_folder",
        "retention_boundary": "fold_complete_delete_allowed",
        "file_count": file_count,
        "byte_count": byte_count,
        "required_completion_gate": "fold_layers_01_10_model_evaluation_complete",
        "requires_artifact_index": True,
        "requires_protected_set_clear": True,
        "requires_quarantine_recheck": True,
        "requires_deletion_receipt": True,
        "preserve_reusable_layer_01_02_source_data": True,
        "deletion_performed": False,
    }


def detect_completed_model_worker_folds(*, manager_root: Path) -> tuple[dict[str, Any], ...]:
    runtime_root = manager_root / "storage" / "runtime"
    if not runtime_root.exists():
        return ()
    candidates: list[dict[str, Any]] = []
    for path in sorted(runtime_root.glob(FOLD_STATE_GLOB)):
        months = _state_months(path)
        if months is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping) or not _is_completed_model_worker_fold(payload):
            continue
        start_month = str(payload.get("start_month") or months[0])
        end_month = str(payload.get("end_month") or months[1])
        candidates.append(
            _backup_candidate(
                fold_id=_fold_id(start_month, end_month),
                start_month=start_month,
                end_month=end_month,
                state_path=path,
            )
        )
    return tuple(candidates)


def detect_fold_scoped_source_cleanup_candidates(
    *,
    root: Path,
    completed_fold_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Find fold-folder source cleanup candidates without mutating storage."""

    source_root = root / FOLD_SCOPED_SOURCE_ROOT
    if not source_root.exists():
        return ()
    completed = set(completed_fold_ids)
    candidates: list[dict[str, Any]] = []
    for folder in sorted(source_root.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name not in completed:
            continue
        candidates.append(_fold_source_cleanup_candidate(fold_id=folder.name, source_folder=folder, root=root))
    return tuple(candidates)


def run_storage_maintenance(
    *,
    root: Path = Path("."),
    archive_root: Path = Path("storage/90_lifecycle/archive"),
    manager_root: Path | None = None,
    apply_local_retention: bool = False,
    include_local_retention: bool = True,
    include_fold_monitor: bool = True,
    generated_at_utc: str | None = None,
) -> StorageMaintenanceSummary:
    root = root.resolve()
    storage_root_inventory = _build_storage_root_inventory(root)
    local_retention_summary = {"archive": 0, "delete": 0, "retain": 0, "skip": 0}
    if include_local_retention:
        retention = plan_retention(root=root, archive_root=archive_root, dry_run=not apply_local_retention)
        if apply_local_retention:
            retention = apply_retention_plan(retention)
        local_retention_summary = retention.summary
    resolved_manager_root = manager_root.resolve() if manager_root is not None else None
    fold_candidates = (
        detect_completed_model_worker_folds(manager_root=resolved_manager_root)
        if include_fold_monitor and resolved_manager_root is not None
        else ()
    )
    completed_fold_ids = tuple(str(candidate["fold_id"]) for candidate in fold_candidates)
    fold_source_cleanup_candidates = detect_fold_scoped_source_cleanup_candidates(
        root=root,
        completed_fold_ids=completed_fold_ids,
    )
    fold_source_cleanup_phase = (
        "ready_for_quarantine_review" if fold_source_cleanup_candidates else "no_fold_scoped_source_cleanup_candidates"
    )
    if not include_fold_monitor:
        fold_source_cleanup_phase = "fold_monitor_skipped"
    return StorageMaintenanceSummary(
        contract_type="storage_scheduled_maintenance_summary",
        generated_at_utc=generated_at_utc or _now_utc(),
        root=str(root),
        local_retention_enabled=include_local_retention,
        local_retention_apply=apply_local_retention,
        local_retention_summary=local_retention_summary,
        storage_root_inventory_summary=_storage_root_inventory_summary(storage_root_inventory),
        storage_root_inventory=storage_root_inventory,
        manager_root=str(resolved_manager_root) if resolved_manager_root is not None else None,
        fold_monitor_enabled=include_fold_monitor and resolved_manager_root is not None,
        completed_fold_count=len(fold_candidates),
        completed_fold_ids=completed_fold_ids,
        fold_backup_candidates=fold_candidates,
        fold_source_cleanup_candidates=fold_source_cleanup_candidates,
        fold_source_cleanup_candidate_count=len(fold_source_cleanup_candidates),
        fold_sql_backup_phase_status="ready_for_storage_backup" if fold_candidates else "no_completed_fold_detected",
        fold_source_cleanup_phase_status=fold_source_cleanup_phase,
        deletion_phase_status="local_retention_only" if include_local_retention else "local_retention_skipped",
        provider_calls_performed=False,
        model_activation_performed=False,
        broker_execution_performed=False,
        account_mutation_performed=False,
    )


def write_storage_maintenance_summary(summary: StorageMaintenanceSummary, *, output_path: Path, root: Path) -> None:
    destination = _resolve(root.resolve(), output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(summary.to_json(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the storage-owned scheduled maintenance pass.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root. Defaults to current directory.")
    parser.add_argument("--archive-root", type=Path, default=Path("storage/90_lifecycle/archive"))
    parser.add_argument("--manager-root", type=Path, help="Manager repository root for fold-state monitoring.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MAINTENANCE_OUTPUT)
    parser.add_argument("--apply-local-retention", action="store_true", help="Archive/delete eligible local runtime files.")
    parser.add_argument("--skip-local-retention", action="store_true", help="Skip local retention planning.")
    parser.add_argument("--skip-fold-monitor", action="store_true", help="Skip direct manager fold-state reads.")
    parser.add_argument("--json", action="store_true", help="Print the summary JSON to stdout.")
    args = parser.parse_args(argv)
    summary = run_storage_maintenance(
        root=args.root,
        archive_root=args.archive_root,
        manager_root=args.manager_root,
        apply_local_retention=args.apply_local_retention,
        include_local_retention=not args.skip_local_retention,
        include_fold_monitor=not args.skip_fold_monitor,
    )
    write_storage_maintenance_summary(summary, output_path=args.output_path, root=args.root)
    if args.json:
        print(summary.to_json(), end="")
    return 0


__all__ = [
    "DEFAULT_MAINTENANCE_OUTPUT",
    "StorageMaintenanceSummary",
    "detect_completed_model_worker_folds",
    "detect_fold_scoped_source_cleanup_candidates",
    "run_storage_maintenance",
    "write_storage_maintenance_summary",
]
