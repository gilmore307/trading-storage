"""Lifecycle planner/executor for dashboard read-model snapshots.

Dashboard snapshots are owner-facing metadata caches, not canonical Layer 1/2
source data.  This helper keeps latest/hot snapshots and can remove older
snapshot files after a reviewed model-run retention window.  It never deletes
``latest.json``, schemas, index rows, Layer 1/2 source artifacts, SQL data, or
non-dashboard paths.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from trading_storage.io import write_text_atomic

from trading_storage.artifact_index import now_utc

DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_OUTPUT = Path("storage/dashboard/lifecycle/dashboard_snapshot_prune_plan.json")
DEFAULT_SUMMARY_OUTPUT = Path("storage/dashboard/lifecycle/dashboard_snapshot_prune_summary.json")
DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_KEEP_LATEST_PER_CONTRACT = 24


@dataclass(frozen=True)
class DashboardSnapshotLifecycleRecord:
    """One dashboard snapshot retention recommendation or deletion receipt row."""

    contract_type: str
    physical_path: str
    generated_at_utc: str
    artifact_size_bytes: int
    action: str
    reason: str
    mutation_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DashboardSnapshotLifecyclePlan:
    """Plan/receipt bundle for dashboard snapshot pruning."""

    contract_type: str
    generated_at: str
    storage_root: str
    max_age_hours: int
    keep_latest_per_contract: int
    apply: bool
    records: tuple[DashboardSnapshotLifecycleRecord, ...]
    approval_ref: str | None = None

    @property
    def summary(self) -> dict[str, Any]:
        action_counts: dict[str, int] = {}
        candidate_bytes = 0
        deleted_bytes = 0
        retained_bytes = 0
        for record in self.records:
            action_counts[record.action] = action_counts.get(record.action, 0) + 1
            if record.action in {"delete_candidate", "deleted"}:
                candidate_bytes += record.artifact_size_bytes
            if record.action == "deleted":
                deleted_bytes += record.artifact_size_bytes
            if record.action.startswith("retain"):
                retained_bytes += record.artifact_size_bytes
        return {
            "contract_type": "dashboard_snapshot_prune_summary",
            "generated_at": self.generated_at,
            "storage_root": self.storage_root,
            "max_age_hours": self.max_age_hours,
            "keep_latest_per_contract": self.keep_latest_per_contract,
            "apply": self.apply,
            "approval_ref": self.approval_ref,
            "record_count": len(self.records),
            "action_counts": dict(sorted(action_counts.items())),
            "candidate_delete_bytes": candidate_bytes,
            "deleted_bytes": deleted_bytes,
            "retained_bytes": retained_bytes,
            "mutation_performed": any(record.mutation_performed for record in self.records),
            "scope": "storage/dashboard/read_models/*/snapshots/**/*.json only",
            "latest_json_deleted": False,
            "schema_deleted": False,
            "index_deleted": False,
            "layer_01_02_data_deleted": False,
            "sql_mutation_performed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "storage_root": self.storage_root,
            "max_age_hours": self.max_age_hours,
            "keep_latest_per_contract": self.keep_latest_per_contract,
            "apply": self.apply,
            "summary": self.summary,
            "approval_ref": self.approval_ref,
            "records": [record.to_dict() for record in self.records],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _parse_snapshot_timestamp(path: Path) -> datetime | None:
    stem = path.stem
    try:
        return datetime.strptime(stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _snapshot_files(storage_root: Path) -> dict[str, list[Path]]:
    read_models_root = storage_root / "dashboard" / "read_models"
    by_contract: dict[str, list[Path]] = {}
    if not read_models_root.exists():
        return by_contract
    for contract_dir in sorted(path for path in read_models_root.iterdir() if path.is_dir()):
        snapshots_root = contract_dir / "snapshots"
        if not snapshots_root.exists():
            continue
        by_contract[contract_dir.name] = sorted(path for path in snapshots_root.rglob("*.json") if path.is_file() and not path.is_symlink())
    return by_contract


def _relative(storage_root: Path, path: Path) -> str:
    return str(path.relative_to(storage_root)).replace("\\", "/")


def _prune_empty_snapshot_dirs(storage_root: Path, path: Path) -> None:
    snapshots_root = path.parents[3] if len(path.parents) >= 4 else None
    if snapshots_root is None or snapshots_root.name != "snapshots":
        return
    current = path.parent
    while current != snapshots_root and current != storage_root:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def build_dashboard_snapshot_lifecycle_plan(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    keep_latest_per_contract: int = DEFAULT_KEEP_LATEST_PER_CONTRACT,
    apply: bool = False,
    generated_at: str | None = None,
    now: datetime | None = None,
    approval_ref: str | None = None,
) -> DashboardSnapshotLifecyclePlan:
    """Plan or apply bounded dashboard snapshot pruning."""

    if max_age_hours < 0:
        raise ValueError("max_age_hours must be >= 0")
    if keep_latest_per_contract < 1:
        raise ValueError("keep_latest_per_contract must be >= 1")
    if apply and not (approval_ref or "").strip():
        raise ValueError("approval_ref is required when applying dashboard snapshot pruning")
    storage_root = Path(storage_root).resolve()
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - timedelta(hours=max_age_hours)
    generated = generated_at or now_utc()
    records: list[DashboardSnapshotLifecycleRecord] = []

    for contract_type, paths in _snapshot_files(storage_root).items():
        decorated: list[tuple[datetime, Path]] = []
        for path in paths:
            timestamp = _parse_snapshot_timestamp(path) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            decorated.append((timestamp, path))
        decorated.sort(key=lambda item: item[0], reverse=True)
        keep_paths = {path for _timestamp, path in decorated[:keep_latest_per_contract]}
        for timestamp, path in decorated:
            stat = path.stat()
            generated_text = timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            relative = _relative(storage_root, path)
            if path in keep_paths:
                records.append(
                    DashboardSnapshotLifecycleRecord(
                        contract_type=contract_type,
                        physical_path=relative,
                        generated_at_utc=generated_text,
                        artifact_size_bytes=stat.st_size,
                        action="retain_recent_snapshot",
                        reason="Within keep_latest_per_contract hot snapshot window.",
                    )
                )
                continue
            if timestamp > cutoff:
                records.append(
                    DashboardSnapshotLifecycleRecord(
                        contract_type=contract_type,
                        physical_path=relative,
                        generated_at_utc=generated_text,
                        artifact_size_bytes=stat.st_size,
                        action="retain_within_ttl",
                        reason="Snapshot is newer than the dashboard metadata retention cutoff.",
                    )
                )
                continue
            action = "delete_candidate"
            mutation = False
            reason = "Older than dashboard metadata retention cutoff and outside hot snapshot window."
            if apply:
                path.unlink()
                _prune_empty_snapshot_dirs(storage_root, path)
                action = "deleted"
                mutation = True
                reason = "Deleted dashboard metadata snapshot after retention cutoff; latest/schema/index were preserved."
            records.append(
                DashboardSnapshotLifecycleRecord(
                    contract_type=contract_type,
                    physical_path=relative,
                    generated_at_utc=generated_text,
                    artifact_size_bytes=stat.st_size,
                    action=action,
                    reason=reason,
                    mutation_performed=mutation,
                )
            )

    return DashboardSnapshotLifecyclePlan(
        contract_type="dashboard_snapshot_prune_plan" if not apply else "dashboard_snapshot_prune_receipt",
        generated_at=generated,
        storage_root=str(storage_root),
        max_age_hours=max_age_hours,
        keep_latest_per_contract=keep_latest_per_contract,
        apply=apply,
        records=tuple(records),
        approval_ref=approval_ref,
    )


def write_dashboard_snapshot_lifecycle_plan(
    plan: DashboardSnapshotLifecyclePlan,
    *,
    output_path: Path,
    summary_path: Path | None = None,
) -> None:
    root = Path(plan.storage_root)
    output = output_path if output_path.is_absolute() else root.parent / output_path if output_path.parts[:1] == ("storage",) else root / output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output, plan.to_json())
    if summary_path is not None:
        summary = summary_path if summary_path.is_absolute() else root.parent / summary_path if summary_path.parts[:1] == ("storage",) else root / summary_path
        summary.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary, plan.summary_json())


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or apply dashboard read-model snapshot pruning.")
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT), help="Storage root containing dashboard/read_models.")
    parser.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS, help="Delete-candidate threshold for snapshots outside the hot keep window.")
    parser.add_argument("--keep-latest-per-contract", type=int, default=DEFAULT_KEEP_LATEST_PER_CONTRACT, help="Minimum recent snapshots to keep per contract.")
    parser.add_argument("--apply", action="store_true", help="Delete eligible dashboard snapshot files. Default is dry-run only.")
    parser.add_argument("--approval-ref", help="Required reviewed approval/reference when --apply is used.")
    parser.add_argument("--write", action="store_true", help="Write plan/receipt JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT), help="Plan/receipt output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_SUMMARY_OUTPUT), help="Summary output path.")
    parser.add_argument("--json", action="store_true", help="Print full plan/receipt JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    plan = build_dashboard_snapshot_lifecycle_plan(
        storage_root=Path(args.storage_root),
        max_age_hours=args.max_age_hours,
        keep_latest_per_contract=args.keep_latest_per_contract,
        apply=args.apply,
        approval_ref=args.approval_ref,
    )
    if args.write:
        write_dashboard_snapshot_lifecycle_plan(plan, output_path=Path(args.output_path), summary_path=Path(args.summary_path))
    if args.json:
        print(plan.to_json(), end="")
    else:
        print(plan.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
