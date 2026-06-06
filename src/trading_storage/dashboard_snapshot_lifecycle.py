"""Lifecycle planner/executor for dashboard read-model snapshots.

Dashboard snapshots are owner-facing metadata caches, not canonical Layer 1/2
source data.  The current default is latest-only: keep no timestamped full
snapshots per read-model contract unless a debugging grace window is explicitly
approved.  This helper removes only timestamped snapshot files after review. It
never deletes ``latest.json``, schemas, index rows, Layer 1/2 source artifacts,
SQL data, or non-dashboard paths.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from trading_storage.io import write_text_atomic

from trading_storage.artifact_index import now_utc

DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_OUTPUT = Path("storage/06_dashboard_cache/lifecycle/dashboard_snapshot_prune_plan.json")
DEFAULT_SUMMARY_OUTPUT = Path("storage/06_dashboard_cache/lifecycle/dashboard_snapshot_prune_summary.json")
DEFAULT_INDEX_PATH = Path("06_dashboard_cache/index/dashboard_read_model_index.jsonl")
DEFAULT_MAX_AGE_HOURS = 0
DEFAULT_KEEP_LATEST_PER_CONTRACT = 0


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
            "scope": "storage/06_dashboard_cache/read_models/*/snapshots/**/*.json only",
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
    read_models_root = storage_root / "06_dashboard_cache" / "read_models"
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


def _has_unresolved_issue_ref(path: Path) -> bool:
    """Return whether a snapshot carries an explicit evidence-retention issue.

    Ordinary dashboard ``issue_refs`` are current-state pointers and are still
    represented by ``latest.json`` or their canonical diagnostic/task roots.
    They should not make every historical dashboard cache snapshot protected.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    issue_refs = payload.get("issue_refs")
    if not isinstance(issue_refs, Sequence) or isinstance(issue_refs, (str, bytes, bytearray)):
        return False
    resolved_statuses = {"resolved", "closed", "completed", "not_planned", "false_positive"}
    for issue in issue_refs:
        if not isinstance(issue, dict):
            continue
        retention_required = bool(
            issue.get("snapshot_retention_required")
            or issue.get("retention_required")
            or issue.get("preserve_snapshot")
            or issue.get("only_remaining_evidence")
        )
        if not retention_required:
            continue
        status = str(issue.get("status") or issue.get("resolution_status") or "open").strip().lower()
        if status not in resolved_statuses:
            return True
    return False


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
    if keep_latest_per_contract < 0:
        raise ValueError("keep_latest_per_contract must be >= 0")
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
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
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
            if max_age_hours > 0 and timestamp > cutoff:
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
            if _has_unresolved_issue_ref(path):
                records.append(
                    DashboardSnapshotLifecycleRecord(
                        contract_type=contract_type,
                        physical_path=relative,
                        generated_at_utc=generated_text,
                        artifact_size_bytes=stat.st_size,
                        action="retain_unresolved_issue_snapshot",
                        reason="Snapshot contains open/unresolved issue_refs and must remain available for incident review.",
                    )
                )
                continue
            action = "delete_candidate"
            mutation = False
            reason = "Outside dashboard hot snapshot count window."
            if max_age_hours > 0:
                reason = "Older than dashboard metadata retention cutoff and outside hot snapshot window."
            if apply:
                path.unlink()
                _prune_empty_snapshot_dirs(storage_root, path)
                action = "deleted"
                mutation = True
                reason = "Deleted dashboard metadata snapshot outside hot snapshot count window; latest/schema/index were preserved."
                if max_age_hours > 0:
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


def compact_dashboard_read_model_index(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    """Remove dashboard index rows whose snapshot files no longer exist."""

    storage_root = Path(storage_root).resolve()
    index_path = storage_root / DEFAULT_INDEX_PATH
    summary: dict[str, Any] = {
        "contract_type": "dashboard_read_model_index_compaction",
        "storage_root": str(storage_root),
        "index_path": str(index_path),
        "input_rows": 0,
        "retained_rows": 0,
        "dropped_rows": 0,
        "input_bytes": index_path.stat().st_size if index_path.exists() else 0,
        "output_bytes": 0,
        "mutation_performed": False,
    }
    if not index_path.exists():
        return summary

    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{index_path.name}.", suffix=".tmp", dir=index_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output, index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                summary["input_rows"] += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    summary["dropped_rows"] += 1
                    continue
                snapshot_uri = str(row.get("snapshot_uri") or "")
                if not snapshot_uri.startswith("storage://trading-storage/"):
                    summary["dropped_rows"] += 1
                    continue
                snapshot_path = storage_root / snapshot_uri.removeprefix("storage://trading-storage/")
                if not snapshot_path.exists():
                    summary["dropped_rows"] += 1
                    continue
                output.write(json.dumps(row, sort_keys=True) + "\n")
                summary["retained_rows"] += 1
        os.replace(temp_name, index_path)
        summary["output_bytes"] = index_path.stat().st_size
        summary["mutation_performed"] = summary["dropped_rows"] > 0 or summary["output_bytes"] != summary["input_bytes"]
    except Exception:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass
        raise
    return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or apply dashboard read-model snapshot pruning.")
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT), help="Storage root containing 06_dashboard_cache/read_models.")
    parser.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS, help="Optional extra age grace for snapshots outside the hot keep window. Default 0 means count-only pruning.")
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
    index_compaction = compact_dashboard_read_model_index(storage_root=Path(args.storage_root)) if args.apply else None
    if args.json:
        payload = plan.to_dict()
        if index_compaction is not None:
            payload["index_compaction"] = index_compaction
        print(json.dumps(payload, indent=2, sort_keys=True) + "\n", end="")
    else:
        summary = plan.summary
        if index_compaction is not None:
            summary = dict(summary)
            summary["index_compaction"] = index_compaction
        print(json.dumps(summary, indent=2, sort_keys=True) + "\n", end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
