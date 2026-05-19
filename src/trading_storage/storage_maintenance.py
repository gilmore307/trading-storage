"""Storage-owned scheduled maintenance runner."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .lifecycle import apply_retention_plan, plan_retention

DEFAULT_MAINTENANCE_OUTPUT = Path("storage/maintenance/storage_maintenance_summary.json")


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
    fold_sql_backup_phase_status: str
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
            "fold_sql_backup_phase_status": self.fold_sql_backup_phase_status,
            "deletion_phase_status": self.deletion_phase_status,
            "provider_calls_performed": self.provider_calls_performed,
            "model_activation_performed": self.model_activation_performed,
            "broker_execution_performed": self.broker_execution_performed,
            "account_mutation_performed": self.account_mutation_performed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def run_storage_maintenance(
    *,
    root: Path = Path("."),
    archive_root: Path = Path("storage/archive"),
    apply_local_retention: bool = False,
    include_local_retention: bool = True,
    generated_at_utc: str | None = None,
) -> StorageMaintenanceSummary:
    root = root.resolve()
    local_retention_summary = {"archive": 0, "delete": 0, "retain": 0, "skip": 0}
    if include_local_retention:
        retention = plan_retention(root=root, archive_root=archive_root, dry_run=not apply_local_retention)
        if apply_local_retention:
            retention = apply_retention_plan(retention)
        local_retention_summary = retention.summary
    return StorageMaintenanceSummary(
        contract_type="storage_scheduled_maintenance_summary",
        generated_at_utc=generated_at_utc or _now_utc(),
        root=str(root),
        local_retention_enabled=include_local_retention,
        local_retention_apply=apply_local_retention,
        local_retention_summary=local_retention_summary,
        fold_sql_backup_phase_status="not_configured",
        deletion_phase_status="local_retention_only",
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
    parser.add_argument("--archive-root", type=Path, default=Path("storage/archive"))
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MAINTENANCE_OUTPUT)
    parser.add_argument("--apply-local-retention", action="store_true", help="Archive/delete eligible local runtime files.")
    parser.add_argument("--skip-local-retention", action="store_true", help="Skip local retention planning.")
    parser.add_argument("--json", action="store_true", help="Print the summary JSON to stdout.")
    args = parser.parse_args(argv)
    summary = run_storage_maintenance(
        root=args.root,
        archive_root=args.archive_root,
        apply_local_retention=args.apply_local_retention,
        include_local_retention=not args.skip_local_retention,
    )
    write_storage_maintenance_summary(summary, output_path=args.output_path, root=args.root)
    if args.json:
        print(summary.to_json(), end="")
    return 0


__all__ = [
    "DEFAULT_MAINTENANCE_OUTPUT",
    "StorageMaintenanceSummary",
    "run_storage_maintenance",
    "write_storage_maintenance_summary",
]
