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
LIFECYCLE_GAP_SELECTORS: tuple[dict[str, Any], ...] = (
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs",
        "artifact_class": "runtime_evidence",
        "issue": "missing_compact_contract",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "replay_run_completed",
        "consumer_or_use": "model promotion replay audit and dashboard model posture",
        "required_followup": "write compact replay run manifest and preserve promotion-linked exceptions before removing verbose decision rows",
    },
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_attribution_runs",
        "artifact_class": "decision_evidence",
        "issue": "duplicate_verbose_evidence",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "post_replay_attribution_completed",
        "consumer_or_use": "residual event governance attribution review",
        "required_followup": "write attribution summary and keep unresolved or promotion-linked runs as exceptions",
    },
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_failure_triage_runs",
        "artifact_class": "decision_evidence",
        "issue": "oversized_verbose_evidence",
        "action": "compact",
        "final_handling_method": "compress",
        "trigger_required": "failure_triage_closed",
        "consumer_or_use": "failure disposition audit",
        "required_followup": "write compact failure-triage decision contract before compressing verbose rows",
    },
    {
        "artifact_ref": "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/_manifests/recent_refresh_runs",
        "artifact_class": "runtime_evidence",
        "issue": "repeated_run_receipts",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "calendar_refresh_completed",
        "consumer_or_use": "TE source provenance and freshness dashboard",
        "required_followup": "write month-level provenance/read-model and preserve canonical TE source rows before rolling duplicate receipts",
    },
    {
        "artifact_ref": "storage/04_execution_artifacts/runtime/realtime_monitor",
        "artifact_class": "runtime_evidence",
        "issue": "unbounded_timestamped_dirs",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "realtime_monitor_window_advanced",
        "consumer_or_use": "realtime signal dashboard and alert diagnostics",
        "required_followup": "write latest/current-window summary and preserve unresolved alert exceptions",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/model_05_option_expression",
        "artifact_class": "runtime_evidence",
        "issue": "per_request_task_key_sprawl",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "provider_stage_completed",
        "consumer_or_use": "provider retry and failure repair during active window",
        "required_followup": "write batch manifest and keep active, failed, retryable, or unresolved task keys",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/provider_task_keys",
        "artifact_class": "runtime_evidence",
        "issue": "per_request_task_key_sprawl",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "provider_stage_completed",
        "consumer_or_use": "provider retry and failure repair during active window",
        "required_followup": "write provider batch manifest and keep active, failed, retryable, or unresolved task keys",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl",
        "artifact_class": "runtime_evidence",
        "issue": "append_only_log_as_read_model",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "scheduler_decision_window_closed",
        "consumer_or_use": "system status dashboard throughput view",
        "required_followup": "write scheduler rollup summary before rolling old JSONL segments",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/stage_coverage",
        "artifact_class": "derived_read_model",
        "issue": "timestamped_detail_without_aggregate",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "stage_coverage_window_closed",
        "consumer_or_use": "historical task progress dashboard",
        "required_followup": "write latest coverage plus aggregate before rolling detailed snapshots",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/stage_run_dashboard",
        "artifact_class": "derived_read_model",
        "issue": "timestamped_detail_without_aggregate",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "stage_run_window_closed",
        "consumer_or_use": "system status dashboard",
        "required_followup": "write latest stage-run summary plus aggregate before rolling detailed snapshots",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/layer_03_target_state_vector/input_materialization",
        "artifact_class": "debug_side_product",
        "issue": "unclear_lineage_rebuildability",
        "action": "retention_update",
        "final_handling_method": None,
        "handling_status": "insufficient_evidence",
        "trigger_required": "fold_or_run_closed",
        "consumer_or_use": "Layer 3 input diagnosis",
        "required_followup": "prove SQL/source lineage and model references before choosing delete or compress",
    },
    {
        "artifact_ref": "storage/03_model_artifacts/runtime/model_05_alpha_confidence",
        "artifact_class": "decision_evidence",
        "issue": "unclear_canonical_owner",
        "action": "retention_update",
        "final_handling_method": None,
        "handling_status": "insufficient_evidence",
        "trigger_required": "model_artifact_role_classified",
        "consumer_or_use": "model evaluation and promotion evidence",
        "required_followup": "classify as canonical model evidence, compressible cold evidence, or rebuildable runtime output",
    },
)
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
    ("05_replay_datasets", "storage/05_replay_datasets", "durable_replay", "Frozen replay datasets, acquisition plans, and replay inputs."),
    ("06_dashboard_cache", "storage/06_dashboard_cache", "managed_cache", "Dashboard read-model current/schema cache."),
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
    lifecycle_gap_audit_summary: dict[str, Any]
    lifecycle_gap_findings: tuple[dict[str, Any], ...]
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
            "lifecycle_gap_audit_summary": self.lifecycle_gap_audit_summary,
            "lifecycle_gap_findings": list(self.lifecycle_gap_findings),
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


def _path_inventory(path: Path) -> dict[str, Any]:
    """Return bounded inventory evidence for a lifecycle selector target."""

    file_count = 0
    directory_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    if not path.exists():
        return {
            "exists": False,
            "file_count": 0,
            "directory_count": 0,
            "byte_count": 0,
            "largest_file_path": None,
            "largest_file_bytes": 0,
        }
    paths = (path,) if path.is_file() else path.rglob("*")
    for candidate in paths:
        if candidate.is_symlink():
            continue
        if candidate.is_dir():
            directory_count += 1
            continue
        if not candidate.is_file():
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        file_count += 1
        byte_count += size
        if size > largest_file_bytes:
            largest_file_bytes = size
            largest_file_path = candidate.as_posix()
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _task_key_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    file_count = 0
    byte_count = 0
    parent_dirs: set[str] = set()
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for candidate in path.rglob("task_key.json"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        file_count += 1
        byte_count += size
        parent_dirs.add(candidate.parent.as_posix())
        if size > largest_file_bytes:
            largest_file_bytes = size
            largest_file_path = candidate.as_posix()
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": len(parent_dirs),
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _lifecycle_gap_inventory(root: Path, artifact_ref: str) -> dict[str, Any]:
    path = root / artifact_ref
    if artifact_ref.endswith("provider_task_keys") or artifact_ref.endswith("model_05_option_expression"):
        return _task_key_inventory(path)
    return _path_inventory(path)


def detect_lifecycle_gap_findings(*, root: Path) -> tuple[dict[str, Any], ...]:
    """Report known unbounded lifecycle classes without mutating storage."""

    findings: list[dict[str, Any]] = []
    for selector in LIFECYCLE_GAP_SELECTORS:
        artifact_ref = selector["artifact_ref"]
        inventory = _lifecycle_gap_inventory(root, artifact_ref)
        if not inventory["exists"] or int(inventory["file_count"]) == 0:
            continue
        findings.append(
            {
                "contract_type": "storage_lifecycle_gap_finding",
                "artifact_ref": artifact_ref,
                "artifact_class": selector["artifact_class"],
                "issue": selector["issue"],
                "action": selector["action"],
                "final_handling_method": selector["final_handling_method"],
                "handling_status": selector.get("handling_status", "selected"),
                "trigger_required": selector["trigger_required"],
                "consumer_or_use": selector["consumer_or_use"],
                "required_followup": selector["required_followup"],
                "file_count": inventory["file_count"],
                "directory_count": inventory["directory_count"],
                "byte_count": inventory["byte_count"],
                "largest_file_path": inventory["largest_file_path"],
                "largest_file_bytes": inventory["largest_file_bytes"],
                "mutation_performed": False,
                "review_required": True,
            }
        )
    return tuple(findings)


def _lifecycle_gap_audit_summary(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "contract_type": "storage_lifecycle_gap_audit_summary",
        "finding_count": len(findings),
        "total_byte_count": sum(int(row.get("byte_count") or 0) for row in findings),
        "total_file_count": sum(int(row.get("file_count") or 0) for row in findings),
        "by_final_handling_method": {
            method: sum(1 for row in findings if row.get("final_handling_method") == method)
            for method in ("delete", "compress", "rolling_retention")
        },
        "pending_final_handling_count": sum(1 for row in findings if not row.get("final_handling_method")),
        "mutation_performed": False,
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
    lifecycle_gap_findings = detect_lifecycle_gap_findings(root=root)
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
        lifecycle_gap_audit_summary=_lifecycle_gap_audit_summary(lifecycle_gap_findings),
        lifecycle_gap_findings=lifecycle_gap_findings,
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
    "detect_lifecycle_gap_findings",
    "run_storage_maintenance",
    "write_storage_maintenance_summary",
]
