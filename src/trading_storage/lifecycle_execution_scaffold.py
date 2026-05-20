"""Non-mutating lifecycle execution scaffold for compression/archive/restore.

This module converts dry-run lifecycle-plan rows into reviewed manifest and
receipt drafts for future executors.  It deliberately performs no compression,
archive export, restore, quarantine, deletion, SQL detach/drop, or artifact-index
mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading_storage.artifact_index import ArtifactIndex, ArtifactIndexRecord, DEFAULT_INDEX_ROOTS, build_artifact_index, now_utc
from trading_storage.io import write_text_atomic
from trading_storage.lifecycle_planner import (
    DEFAULT_POLICY_RULES,
    LifecyclePlanRecord,
    StorageLifecyclePlan,
    load_policy_rules,
    load_protected_set_json,
    plan_storage_lifecycle,
)
from trading_storage.protected_set import load_artifact_index_jsonl
from trading_storage.quarantine_recheck import load_storage_lifecycle_plan_json

DEFAULT_EXECUTION_SCAFFOLD_OUTPUT = Path("storage/90_lifecycle/execution/lifecycle_execution_scaffold.json")
DEFAULT_EXECUTION_SCAFFOLD_SUMMARY_OUTPUT = Path("storage/90_lifecycle/execution/lifecycle_execution_scaffold_summary.json")
EXECUTOR_VERSION = "storage_lifecycle_execution_scaffold_v0_1"


@dataclass(frozen=True)
class CompressionManifestDraft:
    """Draft manifest for a future file/object compression executor."""

    contract_type: str
    manifest_ref: str
    artifact_id: str
    artifact_kind: str
    original_uri: str
    original_path: str
    compressed_uri: str
    compressed_path: str
    codec: str
    read_mode: str
    original_size_bytes: int | None
    compressed_size_bytes: int | None
    original_checksum_sha256: str | None
    compressed_checksum_sha256: str | None
    policy_id: str | None
    rule_id: str | None
    restore_command: str
    generated_at: str
    executor_version: str
    dry_run: bool
    mutation_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompressionReceiptDraft:
    """Draft receipt for a future compression attempt."""

    contract_type: str
    receipt_ref: str
    manifest_ref: str
    artifact_id: str
    policy_id: str | None
    rule_id: str | None
    status: str
    protected_set_check_status: str
    restore_smoke_status: str
    original_uri: str
    compressed_uri: str
    codec: str
    read_mode: str
    original_size_bytes: int | None
    compressed_size_bytes: int | None
    original_checksum_sha256: str | None
    compressed_checksum_sha256: str | None
    executor_version: str
    generated_at: str
    dry_run: bool
    mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SqlArchiveManifestDraft:
    """Draft manifest for a future SQL/file archive executor."""

    contract_type: str
    manifest_ref: str
    artifact_id: str
    artifact_kind: str
    source_ref: str
    source_path: str
    archive_uri: str
    archive_path: str
    archive_format: str
    export_command_class: str
    archive_checksum_sha256: str | None
    row_count: int | None
    schema_check_status: str
    policy_id: str | None
    rule_id: str | None
    restore_command: str
    generated_at: str
    executor_version: str
    dry_run: bool
    mutation_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArchiveReceiptDraft:
    """Draft receipt for a future archive attempt."""

    contract_type: str
    receipt_ref: str
    manifest_ref: str
    artifact_id: str
    policy_id: str | None
    rule_id: str | None
    status: str
    protected_set_check_status: str
    restore_smoke_status: str
    detach_drop_quarantine_status: str
    source_ref: str
    archive_uri: str
    checksum_sha256: str | None
    row_count: int | None
    schema_check_status: str
    executor_version: str
    generated_at: str
    dry_run: bool
    mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreReceiptDraft:
    """Draft receipt for future restore verification."""

    contract_type: str
    receipt_ref: str
    source_manifest_ref: str
    source_artifact_id: str
    restore_mode: str
    restore_destination: str
    checksum_status: str
    schema_check_status: str
    row_count_check_status: str
    status: str
    executor_version: str
    generated_at: str
    dry_run: bool
    mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleExecutionScaffold:
    """Non-mutating manifest/receipt draft bundle for future lifecycle executors."""

    contract_type: str
    generated_at: str
    source_lifecycle_plan_generated_at: str | None
    compression_manifests: tuple[CompressionManifestDraft, ...]
    compression_receipts: tuple[CompressionReceiptDraft, ...]
    archive_manifests: tuple[SqlArchiveManifestDraft, ...]
    archive_receipts: tuple[ArchiveReceiptDraft, ...]
    restore_receipts: tuple[RestoreReceiptDraft, ...]
    skipped_records: tuple[dict[str, Any], ...]

    @property
    def summary(self) -> dict[str, Any]:
        skipped_counts: dict[str, int] = {}
        for row in self.skipped_records:
            action = str(row.get("plan_action", "unknown"))
            skipped_counts[action] = skipped_counts.get(action, 0) + 1
        return {
            "contract_type": "storage_lifecycle_execution_scaffold_summary",
            "generated_at": self.generated_at,
            "source_lifecycle_plan_generated_at": self.source_lifecycle_plan_generated_at,
            "compression_manifest_count": len(self.compression_manifests),
            "compression_receipt_count": len(self.compression_receipts),
            "archive_manifest_count": len(self.archive_manifests),
            "archive_receipt_count": len(self.archive_receipts),
            "restore_receipt_count": len(self.restore_receipts),
            "skipped_record_count": len(self.skipped_records),
            "skipped_action_counts": dict(sorted(skipped_counts.items())),
            "mutation_performed": False,
            "executor_mode": "dry_run_scaffold_only",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "source_lifecycle_plan_generated_at": self.source_lifecycle_plan_generated_at,
            "summary": self.summary,
            "compression_manifests": [row.to_dict() for row in self.compression_manifests],
            "compression_receipts": [row.to_dict() for row in self.compression_receipts],
            "archive_manifests": [row.to_dict() for row in self.archive_manifests],
            "archive_receipts": [row.to_dict() for row in self.archive_receipts],
            "restore_receipts": [row.to_dict() for row in self.restore_receipts],
            "skipped_records": list(self.skipped_records),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _stable_ref(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _compressed_path(record: LifecyclePlanRecord) -> str:
    return f"storage/90_lifecycle/archive/compressed/{record.artifact_id}/{Path(record.physical_path).name}.zst"


def _compressed_uri(record: LifecyclePlanRecord) -> str:
    return "storage://trading-storage/" + _compressed_path(record)


def _archive_path(record: LifecyclePlanRecord) -> str:
    return f"storage/90_lifecycle/archive/sql/{record.artifact_id}.dump.zst"


def _archive_uri(record: LifecyclePlanRecord) -> str:
    return "storage://trading-storage/" + _archive_path(record)


def _compression_restore_command(manifest_ref: str) -> str:
    return f"PYTHONPATH=src python3 scripts/lifecycle/verify_restore_manifest.py --manifest-ref {manifest_ref}"


def _archive_restore_command(manifest_ref: str) -> str:
    return f"PYTHONPATH=src python3 scripts/lifecycle/verify_sql_archive_restore.py --manifest-ref {manifest_ref}"


def _restore_receipt_for_manifest(
    *,
    manifest_ref: str,
    artifact_id: str,
    destination: str,
    generated_at: str,
    reason: str,
) -> RestoreReceiptDraft:
    return RestoreReceiptDraft(
        contract_type="restore_receipt_draft",
        receipt_ref=_stable_ref("restore_receipt", manifest_ref, artifact_id),
        source_manifest_ref=manifest_ref,
        source_artifact_id=artifact_id,
        restore_mode="verification_only",
        restore_destination=destination,
        checksum_status="not_performed_dry_run",
        schema_check_status="not_performed_dry_run",
        row_count_check_status="not_applicable",
        status="planned_not_executed",
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=True,
        mutation_performed=False,
        reason=reason,
    )


def _build_compression(record: LifecyclePlanRecord, generated_at: str) -> tuple[CompressionManifestDraft, CompressionReceiptDraft, RestoreReceiptDraft]:
    manifest_ref = _stable_ref("compression_manifest", record.artifact_id, record.physical_path, record.rule_id)
    compressed_path = _compressed_path(record)
    compressed_uri = _compressed_uri(record)
    manifest = CompressionManifestDraft(
        contract_type="compression_manifest_draft",
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        artifact_kind=record.artifact_kind,
        original_uri=record.artifact_uri,
        original_path=record.physical_path,
        compressed_uri=compressed_uri,
        compressed_path=compressed_path,
        codec="zstd",
        read_mode="restore_required",
        original_size_bytes=record.artifact_size_bytes,
        compressed_size_bytes=None,
        original_checksum_sha256=record.checksum_sha256,
        compressed_checksum_sha256=None,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        restore_command=_compression_restore_command(manifest_ref),
        generated_at=generated_at,
        executor_version=EXECUTOR_VERSION,
        dry_run=True,
        mutation_performed=False,
    )
    receipt = CompressionReceiptDraft(
        contract_type="compression_receipt_draft",
        receipt_ref=_stable_ref("compression_receipt", manifest_ref, record.artifact_id),
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        status="planned_not_executed",
        protected_set_check_status="clear_from_lifecycle_plan",
        restore_smoke_status="not_performed_dry_run",
        original_uri=record.artifact_uri,
        compressed_uri=compressed_uri,
        codec="zstd",
        read_mode="restore_required",
        original_size_bytes=record.artifact_size_bytes,
        compressed_size_bytes=None,
        original_checksum_sha256=record.checksum_sha256,
        compressed_checksum_sha256=None,
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=True,
        mutation_performed=False,
        reason="Compression candidate scaffold only; no compressed bytes were written.",
    )
    restore = _restore_receipt_for_manifest(
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        destination=f"storage/restore_smoke/compression/{record.artifact_id}",
        generated_at=generated_at,
        reason="Restore smoke is required for restore-required compressed output, but was not executed in scaffold mode.",
    )
    return manifest, receipt, restore


def _build_archive(record: LifecyclePlanRecord, generated_at: str) -> tuple[SqlArchiveManifestDraft, ArchiveReceiptDraft, RestoreReceiptDraft]:
    manifest_ref = _stable_ref("sql_archive_manifest", record.artifact_id, record.physical_path, record.rule_id)
    archive_path = _archive_path(record)
    archive_uri = _archive_uri(record)
    manifest = SqlArchiveManifestDraft(
        contract_type="sql_archive_manifest_draft",
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        artifact_kind=record.artifact_kind,
        source_ref=record.artifact_uri,
        source_path=record.physical_path,
        archive_uri=archive_uri,
        archive_path=archive_path,
        archive_format="pg_dump_custom_zstd_or_reviewed_export",
        export_command_class="review_required_export",
        archive_checksum_sha256=None,
        row_count=None,
        schema_check_status="not_performed_dry_run",
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        restore_command=_archive_restore_command(manifest_ref),
        generated_at=generated_at,
        executor_version=EXECUTOR_VERSION,
        dry_run=True,
        mutation_performed=False,
    )
    receipt = ArchiveReceiptDraft(
        contract_type="archive_receipt_draft",
        receipt_ref=_stable_ref("archive_receipt", manifest_ref, record.artifact_id),
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        status="planned_not_executed",
        protected_set_check_status="clear_from_lifecycle_plan",
        restore_smoke_status="not_performed_dry_run",
        detach_drop_quarantine_status="not_started",
        source_ref=record.artifact_uri,
        archive_uri=archive_uri,
        checksum_sha256=None,
        row_count=None,
        schema_check_status="not_performed_dry_run",
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=True,
        mutation_performed=False,
        reason="Archive candidate scaffold only; no export/archive bytes were written and no online SQL object was detached or dropped.",
    )
    restore = _restore_receipt_for_manifest(
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        destination=f"storage/restore_smoke/archive/{record.artifact_id}",
        generated_at=generated_at,
        reason="Archive restore smoke is required before detach/drop, but was not executed in scaffold mode.",
    )
    return manifest, receipt, restore


def build_lifecycle_execution_scaffold(
    lifecycle_plan: StorageLifecyclePlan,
    *,
    generated_at: str | None = None,
) -> LifecycleExecutionScaffold:
    """Build non-mutating manifest/receipt drafts from lifecycle-plan actions."""

    generated = generated_at or now_utc()
    compression_manifests: list[CompressionManifestDraft] = []
    compression_receipts: list[CompressionReceiptDraft] = []
    archive_manifests: list[SqlArchiveManifestDraft] = []
    archive_receipts: list[ArchiveReceiptDraft] = []
    restore_receipts: list[RestoreReceiptDraft] = []
    skipped_records: list[dict[str, Any]] = []

    for record in lifecycle_plan.records:
        if record.protected or record.protected_reason_codes:
            skipped_records.append(
                {
                    "artifact_id": record.artifact_id,
                    "artifact_uri": record.artifact_uri,
                    "physical_path": record.physical_path,
                    "plan_action": record.action,
                    "skip_reason": "protected_by_lifecycle_plan",
                    "protected_reason_codes": tuple(record.protected_reason_codes),
                }
            )
            continue
        if record.action == "compress_candidate":
            manifest, receipt, restore = _build_compression(record, generated)
            compression_manifests.append(manifest)
            compression_receipts.append(receipt)
            restore_receipts.append(restore)
            continue
        if record.action == "archive_candidate":
            manifest, receipt, restore = _build_archive(record, generated)
            archive_manifests.append(manifest)
            archive_receipts.append(receipt)
            restore_receipts.append(restore)
            continue
        skipped_records.append(
            {
                "artifact_id": record.artifact_id,
                "artifact_uri": record.artifact_uri,
                "physical_path": record.physical_path,
                "plan_action": record.action,
                "skip_reason": "no_execution_scaffold_for_plan_action",
                "protected_reason_codes": tuple(record.protected_reason_codes),
            }
        )

    return LifecycleExecutionScaffold(
        contract_type="storage_lifecycle_execution_scaffold",
        generated_at=generated,
        source_lifecycle_plan_generated_at=lifecycle_plan.generated_at,
        compression_manifests=tuple(compression_manifests),
        compression_receipts=tuple(compression_receipts),
        archive_manifests=tuple(archive_manifests),
        archive_receipts=tuple(archive_receipts),
        restore_receipts=tuple(restore_receipts),
        skipped_records=tuple(skipped_records),
    )


def write_lifecycle_execution_scaffold(
    scaffold: LifecycleExecutionScaffold,
    *,
    output_path: Path,
    summary_path: Path | None = None,
) -> None:
    """Write scaffold JSON and optional summary JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, scaffold.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, scaffold.summary_json())


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _build_or_load_lifecycle_plan(args: argparse.Namespace, root: Path) -> StorageLifecyclePlan:
    if args.lifecycle_plan_json:
        return load_storage_lifecycle_plan_json(_resolve_path(root, Path(args.lifecycle_plan_json)))
    if args.index_jsonl:
        index_or_records: ArtifactIndex | Sequence[ArtifactIndexRecord] = load_artifact_index_jsonl(_resolve_path(root, Path(args.index_jsonl)))
    else:
        index_or_records = build_artifact_index(root=root, include_roots=tuple(args.include_roots or DEFAULT_INDEX_ROOTS))
    protected_set = load_protected_set_json(_resolve_path(root, Path(args.protected_set_json))) if args.protected_set_json else None
    rules = load_policy_rules(_resolve_path(root, Path(args.policy_file))) if args.policy_file else DEFAULT_POLICY_RULES
    return plan_storage_lifecycle(index_or_records, protected_set=protected_set, rules=rules)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build non-mutating compression/archive/restore lifecycle execution scaffold.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--lifecycle-plan-json", help="Existing lifecycle-plan JSON path. Default builds a live dry-run plan.")
    parser.add_argument("--index-jsonl", help="Existing artifact-index JSONL path used when building a plan.")
    parser.add_argument("--protected-set-json", help="Protected-set JSON path used when building a plan.")
    parser.add_argument("--policy-file", help="JSON lifecycle policy file used when building a plan.")
    parser.add_argument("--include-root", action="append", dest="include_roots", help="Relative root/file for live artifact-index scan. Ignored when --lifecycle-plan-json or --index-jsonl is used.")
    parser.add_argument("--write", action="store_true", help="Write scaffold JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_EXECUTION_SCAFFOLD_OUTPUT), help="Relative/absolute scaffold JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_EXECUTION_SCAFFOLD_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full scaffold JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    plan = _build_or_load_lifecycle_plan(args, root)
    scaffold = build_lifecycle_execution_scaffold(plan)
    if args.write:
        write_lifecycle_execution_scaffold(
            scaffold,
            output_path=_resolve_path(root, Path(args.output_path)),
            summary_path=_resolve_path(root, Path(args.summary_path)),
        )
    if args.json:
        print(scaffold.to_json(), end="")
    else:
        print(scaffold.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
