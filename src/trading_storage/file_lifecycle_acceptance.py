"""One-pass safe file lifecycle acceptance for storage-owned filesystem artifacts.

The acceptance chains the current reviewed file lifecycle helpers:
artifact index -> protected set -> lifecycle plan -> quarantine/recheck evidence ->
execution scaffold -> optional compressed-copy execution -> dashboard snapshot prune
plan. It deliberately does not delete originals, move quarantine files, mutate SQL,
update artifact-index rows, activate models, or touch broker/account state.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from trading_storage.io import write_text_atomic
from trading_storage.artifact_index import (
    DEFAULT_INDEX_OUTPUT,
    DEFAULT_INDEX_ROOTS,
    DEFAULT_SUMMARY_OUTPUT as DEFAULT_INDEX_SUMMARY_OUTPUT,
    build_artifact_index,
    now_utc,
    write_artifact_index,
)
from trading_storage.dashboard_snapshot_lifecycle import (
    DEFAULT_KEEP_LATEST_PER_CONTRACT,
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_OUTPUT as DEFAULT_DASHBOARD_PRUNE_OUTPUT,
    DEFAULT_STORAGE_ROOT as DEFAULT_DASHBOARD_STORAGE_ROOT,
    DEFAULT_SUMMARY_OUTPUT as DEFAULT_DASHBOARD_PRUNE_SUMMARY_OUTPUT,
    build_dashboard_snapshot_lifecycle_plan,
    write_dashboard_snapshot_lifecycle_plan,
)
from trading_storage.lifecycle_execution_scaffold import (
    DEFAULT_EXECUTION_SCAFFOLD_OUTPUT,
    DEFAULT_EXECUTION_SCAFFOLD_SUMMARY_OUTPUT,
    build_lifecycle_execution_scaffold,
    write_lifecycle_execution_scaffold,
)
from trading_storage.lifecycle_planner import (
    DEFAULT_LIFECYCLE_PLAN_OUTPUT,
    DEFAULT_LIFECYCLE_PLAN_SUMMARY_OUTPUT,
    plan_storage_lifecycle,
    write_storage_lifecycle_plan,
)
from trading_storage.protected_set import (
    DEFAULT_PROTECTED_SET_OUTPUT,
    DEFAULT_PROTECTED_SET_SUMMARY_OUTPUT,
    build_protected_set,
    write_protected_set,
)
from trading_storage.quarantine_recheck import (
    DEFAULT_QUARANTINE_RECHECK_OUTPUT,
    DEFAULT_QUARANTINE_RECHECK_SUMMARY_OUTPUT,
    build_quarantine_recheck_evidence,
    write_quarantine_recheck_evidence,
)
from trading_storage.single_file_compression import (
    DEFAULT_SINGLE_FILE_COMPRESSION_OUTPUT,
    DEFAULT_SINGLE_FILE_COMPRESSION_SUMMARY_OUTPUT,
    execute_single_file_compression,
    write_single_file_compression_result,
)

DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_OUTPUT = Path("storage/lifecycle_execution/file_lifecycle_acceptance.json")
DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_SUMMARY_OUTPUT = Path("storage/lifecycle_execution/file_lifecycle_acceptance_summary.json")


@dataclass(frozen=True)
class FileLifecycleAcceptance:
    """Summary envelope for a complete safe file-lifecycle pass."""

    contract_type: str
    generated_at: str
    root: str
    include_roots: tuple[str, ...]
    artifact_index_summary: dict[str, Any]
    protected_set_summary: dict[str, Any]
    lifecycle_plan_summary: dict[str, Any]
    quarantine_recheck_summary: dict[str, Any]
    execution_scaffold_summary: dict[str, Any]
    single_file_compression_summary: dict[str, Any]
    dashboard_snapshot_prune_summary: dict[str, Any]
    outputs: dict[str, str]
    apply_compression: bool
    apply_dashboard_prune: bool
    mutation_performed: bool
    compressed_copy_mutation_performed: bool
    dashboard_snapshot_delete_performed: bool
    delete_original_performed: bool
    artifact_index_updated: bool
    quarantine_move_performed: bool
    sql_mutation_performed: bool
    model_activation_performed: bool
    broker_execution_performed: bool
    account_mutation_performed: bool
    storage_cleanup_hold_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "root": self.root,
            "include_roots": list(self.include_roots),
            "artifact_index_summary": self.artifact_index_summary,
            "protected_set_summary": self.protected_set_summary,
            "lifecycle_plan_summary": self.lifecycle_plan_summary,
            "quarantine_recheck_summary": self.quarantine_recheck_summary,
            "execution_scaffold_summary": self.execution_scaffold_summary,
            "single_file_compression_summary": self.single_file_compression_summary,
            "dashboard_snapshot_prune_summary": self.dashboard_snapshot_prune_summary,
            "outputs": dict(sorted(self.outputs.items())),
            "apply_compression": self.apply_compression,
            "apply_dashboard_prune": self.apply_dashboard_prune,
            "mutation_performed": self.mutation_performed,
            "compressed_copy_mutation_performed": self.compressed_copy_mutation_performed,
            "dashboard_snapshot_delete_performed": self.dashboard_snapshot_delete_performed,
            "delete_original_performed": self.delete_original_performed,
            "artifact_index_updated": self.artifact_index_updated,
            "quarantine_move_performed": self.quarantine_move_performed,
            "sql_mutation_performed": self.sql_mutation_performed,
            "model_activation_performed": self.model_activation_performed,
            "broker_execution_performed": self.broker_execution_performed,
            "account_mutation_performed": self.account_mutation_performed,
            "storage_cleanup_hold_reason": self.storage_cleanup_hold_reason,
        }

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "contract_type": "storage_file_lifecycle_acceptance_summary_v1",
            "generated_at": self.generated_at,
            "root": self.root,
            "include_roots": list(self.include_roots),
            "artifact_record_count": self.artifact_index_summary.get("record_count", 0),
            "artifact_total_size_bytes": self.artifact_index_summary.get("total_artifact_size_bytes", 0),
            "protected_count": self.protected_set_summary.get("protected_count", 0),
            "lifecycle_action_counts": self.lifecycle_plan_summary.get("action_counts", {}),
            "compression_status_counts": self.single_file_compression_summary.get("status_counts", {}),
            "compression_skipped_reason_counts": self.single_file_compression_summary.get("skipped_reason_counts", {}),
            "dashboard_prune_action_counts": self.dashboard_snapshot_prune_summary.get("action_counts", {}),
            "dashboard_prune_candidate_delete_bytes": self.dashboard_snapshot_prune_summary.get("candidate_delete_bytes", 0),
            "apply_compression": self.apply_compression,
            "apply_dashboard_prune": self.apply_dashboard_prune,
            "mutation_performed": self.mutation_performed,
            "compressed_copy_mutation_performed": self.compressed_copy_mutation_performed,
            "dashboard_snapshot_delete_performed": self.dashboard_snapshot_delete_performed,
            "delete_original_performed": self.delete_original_performed,
            "artifact_index_updated": self.artifact_index_updated,
            "quarantine_move_performed": self.quarantine_move_performed,
            "sql_mutation_performed": self.sql_mutation_performed,
            "model_activation_performed": self.model_activation_performed,
            "broker_execution_performed": self.broker_execution_performed,
            "account_mutation_performed": self.account_mutation_performed,
            "storage_cleanup_hold_reason": self.storage_cleanup_hold_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _output_map(root: Path) -> dict[str, str]:
    paths = {
        "artifact_index": DEFAULT_INDEX_OUTPUT,
        "artifact_index_summary": DEFAULT_INDEX_SUMMARY_OUTPUT,
        "protected_set": DEFAULT_PROTECTED_SET_OUTPUT,
        "protected_set_summary": DEFAULT_PROTECTED_SET_SUMMARY_OUTPUT,
        "lifecycle_plan": DEFAULT_LIFECYCLE_PLAN_OUTPUT,
        "lifecycle_plan_summary": DEFAULT_LIFECYCLE_PLAN_SUMMARY_OUTPUT,
        "quarantine_recheck": DEFAULT_QUARANTINE_RECHECK_OUTPUT,
        "quarantine_recheck_summary": DEFAULT_QUARANTINE_RECHECK_SUMMARY_OUTPUT,
        "execution_scaffold": DEFAULT_EXECUTION_SCAFFOLD_OUTPUT,
        "execution_scaffold_summary": DEFAULT_EXECUTION_SCAFFOLD_SUMMARY_OUTPUT,
        "single_file_compression": DEFAULT_SINGLE_FILE_COMPRESSION_OUTPUT,
        "single_file_compression_summary": DEFAULT_SINGLE_FILE_COMPRESSION_SUMMARY_OUTPUT,
        "dashboard_snapshot_prune": DEFAULT_DASHBOARD_PRUNE_OUTPUT,
        "dashboard_snapshot_prune_summary": DEFAULT_DASHBOARD_PRUNE_SUMMARY_OUTPUT,
        "file_lifecycle_acceptance": DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_OUTPUT,
        "file_lifecycle_acceptance_summary": DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_SUMMARY_OUTPUT,
    }
    return {key: str(_resolve(root, value)) for key, value in paths.items()}


def build_file_lifecycle_acceptance(
    *,
    root: Path = Path("."),
    include_roots: Sequence[str] = DEFAULT_INDEX_ROOTS,
    apply_compression: bool = False,
    overwrite_compression: bool = False,
    apply_dashboard_prune: bool = False,
    dashboard_prune_approval_ref: str | None = None,
    dashboard_max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    dashboard_keep_latest_per_contract: int = DEFAULT_KEEP_LATEST_PER_CONTRACT,
    generated_at: str | None = None,
) -> FileLifecycleAcceptance:
    """Run the complete safe file-lifecycle pass and write all evidence outputs."""

    root = root.resolve()
    generated = generated_at or now_utc()
    include_roots = tuple(include_roots or DEFAULT_INDEX_ROOTS)

    index = build_artifact_index(root=root, include_roots=include_roots, generated_at=generated)
    protected_set = build_protected_set(index, generated_at=generated)
    lifecycle_plan = plan_storage_lifecycle(index, protected_set=protected_set, generated_at=generated)
    quarantine = build_quarantine_recheck_evidence(lifecycle_plan, final_protected_set=protected_set, generated_at=generated)
    scaffold = build_lifecycle_execution_scaffold(lifecycle_plan, generated_at=generated)
    compression = execute_single_file_compression(
        lifecycle_plan,
        root=root,
        apply=apply_compression,
        overwrite=overwrite_compression,
        generated_at=generated,
    )
    dashboard_prune = build_dashboard_snapshot_lifecycle_plan(
        storage_root=root / DEFAULT_DASHBOARD_STORAGE_ROOT,
        max_age_hours=dashboard_max_age_hours,
        keep_latest_per_contract=dashboard_keep_latest_per_contract,
        apply=apply_dashboard_prune,
        generated_at=generated,
        approval_ref=dashboard_prune_approval_ref,
    )

    write_artifact_index(index, index_path=_resolve(root, DEFAULT_INDEX_OUTPUT), summary_path=_resolve(root, DEFAULT_INDEX_SUMMARY_OUTPUT))
    write_protected_set(protected_set, output_path=_resolve(root, DEFAULT_PROTECTED_SET_OUTPUT), summary_path=_resolve(root, DEFAULT_PROTECTED_SET_SUMMARY_OUTPUT))
    write_storage_lifecycle_plan(lifecycle_plan, output_path=_resolve(root, DEFAULT_LIFECYCLE_PLAN_OUTPUT), summary_path=_resolve(root, DEFAULT_LIFECYCLE_PLAN_SUMMARY_OUTPUT))
    write_quarantine_recheck_evidence(quarantine, output_path=_resolve(root, DEFAULT_QUARANTINE_RECHECK_OUTPUT), summary_path=_resolve(root, DEFAULT_QUARANTINE_RECHECK_SUMMARY_OUTPUT))
    write_lifecycle_execution_scaffold(scaffold, output_path=_resolve(root, DEFAULT_EXECUTION_SCAFFOLD_OUTPUT), summary_path=_resolve(root, DEFAULT_EXECUTION_SCAFFOLD_SUMMARY_OUTPUT))
    write_single_file_compression_result(compression, output_path=_resolve(root, DEFAULT_SINGLE_FILE_COMPRESSION_OUTPUT), summary_path=_resolve(root, DEFAULT_SINGLE_FILE_COMPRESSION_SUMMARY_OUTPUT))
    write_dashboard_snapshot_lifecycle_plan(
        dashboard_prune,
        output_path=_resolve(root, DEFAULT_DASHBOARD_PRUNE_OUTPUT),
        summary_path=_resolve(root, DEFAULT_DASHBOARD_PRUNE_SUMMARY_OUTPUT),
    )

    compressed_copy_mutation = bool(compression.summary.get("mutation_performed"))
    dashboard_delete_mutation = bool(dashboard_prune.summary.get("mutation_performed"))
    acceptance = FileLifecycleAcceptance(
        contract_type="storage_file_lifecycle_acceptance_v1",
        generated_at=generated,
        root=str(root),
        include_roots=include_roots,
        artifact_index_summary=index.summary,
        protected_set_summary=protected_set.summary,
        lifecycle_plan_summary=lifecycle_plan.summary,
        quarantine_recheck_summary=quarantine.summary,
        execution_scaffold_summary=scaffold.summary,
        single_file_compression_summary=compression.summary,
        dashboard_snapshot_prune_summary=dashboard_prune.summary,
        outputs=_output_map(root),
        apply_compression=apply_compression,
        apply_dashboard_prune=apply_dashboard_prune,
        mutation_performed=compressed_copy_mutation or dashboard_delete_mutation,
        compressed_copy_mutation_performed=compressed_copy_mutation,
        dashboard_snapshot_delete_performed=dashboard_delete_mutation,
        delete_original_performed=False,
        artifact_index_updated=False,
        quarantine_move_performed=False,
        sql_mutation_performed=False,
        model_activation_performed=False,
        broker_execution_performed=False,
        account_mutation_performed=False,
        storage_cleanup_hold_reason=(
            "Dashboard/model-run deletion remains dry-run-only until event-risk-governor regeneration and downstream review close; "
            "this acceptance may write compressed copies for approved compress_candidate files only."
        ),
    )
    _resolve(root, DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(_resolve(root, DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_OUTPUT), acceptance.to_json())
    write_text_atomic(_resolve(root, DEFAULT_FILE_LIFECYCLE_ACCEPTANCE_SUMMARY_OUTPUT), acceptance.summary_json())
    return acceptance


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the complete safe storage file-lifecycle acceptance pass.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--include-root", action="append", dest="include_roots", help="Relative root/file to include in the durable artifact index. Defaults to storage/artifacts.")
    parser.add_argument("--apply-compression", action="store_true", help="Write zstd compressed copies for eligible unprotected compress_candidate rows. Originals are preserved.")
    parser.add_argument("--overwrite-compression", action="store_true", help="Allow replacing existing compressed copies for eligible compression rows.")
    parser.add_argument("--apply-dashboard-prune", action="store_true", help="Delete eligible dashboard snapshot metadata. Use only after event regeneration review and explicit approval.")
    parser.add_argument("--dashboard-prune-approval-ref", help="Required reviewed approval/reference when --apply-dashboard-prune is used.")
    parser.add_argument("--dashboard-max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--dashboard-keep-latest-per-contract", type=int, default=DEFAULT_KEEP_LATEST_PER_CONTRACT)
    parser.add_argument("--json", action="store_true", help="Print full acceptance JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    acceptance = build_file_lifecycle_acceptance(
        root=Path(args.root),
        include_roots=tuple(args.include_roots or DEFAULT_INDEX_ROOTS),
        apply_compression=args.apply_compression,
        overwrite_compression=args.overwrite_compression,
        apply_dashboard_prune=args.apply_dashboard_prune,
        dashboard_prune_approval_ref=args.dashboard_prune_approval_ref,
        dashboard_max_age_hours=args.dashboard_max_age_hours,
        dashboard_keep_latest_per_contract=args.dashboard_keep_latest_per_contract,
    )
    print(acceptance.to_json() if args.json else acceptance.summary_json(), end="")
    return 0


__all__ = [
    "FileLifecycleAcceptance",
    "build_file_lifecycle_acceptance",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
