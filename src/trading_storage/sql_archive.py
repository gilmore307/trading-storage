"""Reviewed SQL/archive file executor and restore verifier.

This module implements the first non-service storage archive executor.  It is
intentionally narrow: it only archives already-materialized file exports selected
by a lifecycle plan as `archive_candidate`.  It never connects to a database,
exports live SQL, detaches/drops SQL objects, mutates an artifact index,
quarantines files, deletes files, activates models, or touches broker/account
state.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading_storage.artifact_index import ArtifactIndex, ArtifactIndexRecord, DEFAULT_INDEX_ROOTS, build_artifact_index, now_utc, sha256_file
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

DEFAULT_SQL_ARCHIVE_OUTPUT = Path("storage/90_lifecycle/execution/sql_archive_result.json")
DEFAULT_SQL_ARCHIVE_SUMMARY_OUTPUT = Path("storage/90_lifecycle/execution/sql_archive_summary.json")
DEFAULT_SQL_ARCHIVE_RESTORE_OUTPUT = Path("storage/90_lifecycle/execution/sql_archive_restore_verification.json")
DEFAULT_SQL_ARCHIVE_RESTORE_SUMMARY_OUTPUT = Path("storage/90_lifecycle/execution/sql_archive_restore_verification_summary.json")
EXECUTOR_VERSION = "storage_sql_archive_executor_v0_1"
RESTORE_VERIFIER_VERSION = "storage_sql_archive_restore_verifier_v0_1"


@dataclass(frozen=True)
class SqlArchiveManifest:
    """Manifest for a planned or executed file-backed SQL archive copy."""

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
    source_checksum_sha256: str | None
    archive_checksum_sha256: str | None
    source_size_bytes: int | None
    archive_size_bytes: int | None
    row_count: int | None
    schema_check_status: str
    policy_id: str | None
    rule_id: str | None
    restore_command: str
    generated_at: str
    executor_version: str
    dry_run: bool
    mutation_performed: bool
    sql_mutation_performed: bool
    artifact_index_updated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SqlArchiveReceipt:
    """Receipt for a planned, successful, failed, or skipped archive attempt."""

    contract_type: str
    receipt_ref: str
    manifest_ref: str | None
    artifact_id: str
    policy_id: str | None
    rule_id: str | None
    status: str
    protected_set_check_status: str
    restore_smoke_status: str
    detach_drop_quarantine_status: str
    source_ref: str
    archive_uri: str | None
    checksum_sha256: str | None
    row_count: int | None
    schema_check_status: str
    executor_version: str
    generated_at: str
    dry_run: bool
    mutation_performed: bool
    sql_mutation_performed: bool
    artifact_index_updated: bool
    source_preserved: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SqlArchiveRestoreReceipt:
    """Receipt for archive decompression/checksum verification."""

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
    sql_mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SqlArchiveResult:
    """Result bundle for the file-backed SQL archive executor."""

    contract_type: str
    generated_at: str
    source_lifecycle_plan_generated_at: str | None
    apply: bool
    manifests: tuple[SqlArchiveManifest, ...]
    receipts: tuple[SqlArchiveReceipt, ...]
    restore_receipts: tuple[SqlArchiveRestoreReceipt, ...]
    skipped_records: tuple[dict[str, Any], ...]

    @property
    def summary(self) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        skipped_counts: dict[str, int] = {}
        mutation_count = 0
        sql_mutation_count = 0
        for receipt in self.receipts:
            status_counts[receipt.status] = status_counts.get(receipt.status, 0) + 1
            if receipt.mutation_performed:
                mutation_count += 1
            if receipt.sql_mutation_performed:
                sql_mutation_count += 1
        for row in self.skipped_records:
            reason = str(row.get("skip_reason", "unknown"))
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
        return {
            "contract_type": "storage_sql_archive_summary",
            "generated_at": self.generated_at,
            "source_lifecycle_plan_generated_at": self.source_lifecycle_plan_generated_at,
            "apply": self.apply,
            "manifest_count": len(self.manifests),
            "receipt_count": len(self.receipts),
            "restore_receipt_count": len(self.restore_receipts),
            "skipped_record_count": len(self.skipped_records),
            "status_counts": dict(sorted(status_counts.items())),
            "skipped_reason_counts": dict(sorted(skipped_counts.items())),
            "mutation_performed": mutation_count > 0,
            "mutation_count": mutation_count,
            "sql_mutation_performed": sql_mutation_count > 0,
            "sql_mutation_count": sql_mutation_count,
            "source_delete_performed": False,
            "artifact_index_updated": False,
            "quarantine_move_performed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "source_lifecycle_plan_generated_at": self.source_lifecycle_plan_generated_at,
            "apply": self.apply,
            "summary": self.summary,
            "manifests": [row.to_dict() for row in self.manifests],
            "receipts": [row.to_dict() for row in self.receipts],
            "restore_receipts": [row.to_dict() for row in self.restore_receipts],
            "skipped_records": list(self.skipped_records),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class SqlArchiveRestoreVerification:
    """Verification bundle for existing SQL archive manifests."""

    contract_type: str
    generated_at: str
    source_archive_result_generated_at: str | None
    receipts: tuple[SqlArchiveRestoreReceipt, ...]
    skipped_records: tuple[dict[str, Any], ...]

    @property
    def summary(self) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        skipped_counts: dict[str, int] = {}
        for receipt in self.receipts:
            status_counts[receipt.status] = status_counts.get(receipt.status, 0) + 1
        for row in self.skipped_records:
            reason = str(row.get("skip_reason", "unknown"))
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
        return {
            "contract_type": "storage_sql_archive_restore_verification_summary",
            "generated_at": self.generated_at,
            "source_archive_result_generated_at": self.source_archive_result_generated_at,
            "receipt_count": len(self.receipts),
            "skipped_record_count": len(self.skipped_records),
            "status_counts": dict(sorted(status_counts.items())),
            "skipped_reason_counts": dict(sorted(skipped_counts.items())),
            "mutation_performed": False,
            "sql_mutation_performed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "source_archive_result_generated_at": self.source_archive_result_generated_at,
            "summary": self.summary,
            "receipts": [row.to_dict() for row in self.receipts],
            "skipped_records": list(self.skipped_records),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _stable_ref(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _artifact_identity_hash(record: LifecyclePlanRecord) -> str:
    return hashlib.sha256(
        "\0".join((record.artifact_id, record.artifact_uri, record.physical_path, record.checksum_sha256 or "")).encode("utf-8")
    ).hexdigest()[:20]


def _archive_relative_path(record: LifecyclePlanRecord) -> Path:
    return Path("storage") / "archive" / "sql" / _artifact_identity_hash(record) / (Path(record.physical_path).name + ".archive.json.gz")


def _archive_uri(record: LifecyclePlanRecord) -> str:
    return "storage://trading-storage/" + str(_archive_relative_path(record)).replace("\\", "/")


def _restore_command(manifest_ref: str) -> str:
    return f"PYTHONPATH=src python3 scripts/lifecycle/verify_sql_archive_restore.py --manifest-ref {manifest_ref}"


def _resolve_repo_file(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe artifact path: {relative_path!r}")
    resolved = (root / path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError(f"artifact path escapes root: {relative_path!r}")
    return resolved


def _gzip_copy(source: Path, destination: Path, *, overwrite: bool) -> None:
    if destination.exists() and not overwrite:
        raise FileExistsError(f"archive output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("wb") as raw_dst:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_dst, mtime=0) as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)


def _sha256_decompressed_gzip(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _restore_receipt(
    *,
    manifest_ref: str,
    artifact_id: str,
    generated_at: str,
    dry_run: bool,
    checksum_status: str,
    status: str,
    reason: str,
) -> SqlArchiveRestoreReceipt:
    return SqlArchiveRestoreReceipt(
        contract_type="restore_receipt" if not dry_run else "restore_receipt_draft",
        receipt_ref=_stable_ref("sql_archive_restore_receipt", manifest_ref, artifact_id, status, checksum_status),
        source_manifest_ref=manifest_ref,
        source_artifact_id=artifact_id,
        restore_mode="verification_only",
        restore_destination=f"storage/restore_smoke/sql_archive/{artifact_id}",
        checksum_status=checksum_status,
        schema_check_status="not_applicable_file_backed_archive",
        row_count_check_status="not_applicable_file_backed_archive",
        status=status,
        executor_version=RESTORE_VERIFIER_VERSION if not dry_run else EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=dry_run,
        mutation_performed=False,
        sql_mutation_performed=False,
        reason=reason,
    )


def _manifest_for_record(
    record: LifecyclePlanRecord,
    *,
    generated_at: str,
    dry_run: bool,
    archive_checksum: str | None,
    archive_size: int | None,
) -> SqlArchiveManifest:
    manifest_ref = _stable_ref("sql_archive_manifest", record.artifact_id, record.physical_path, record.rule_id, record.checksum_sha256)
    archive_path = _archive_relative_path(record)
    return SqlArchiveManifest(
        contract_type="sql_archive_manifest" if not dry_run else "sql_archive_manifest_draft",
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        artifact_kind=record.artifact_kind,
        source_ref=record.artifact_uri,
        source_path=record.physical_path,
        archive_uri=_archive_uri(record),
        archive_path=str(archive_path).replace("\\", "/"),
        archive_format="gzip_file_backed_reviewed_export",
        export_command_class="reviewed_file_export_copy",
        source_checksum_sha256=record.checksum_sha256,
        archive_checksum_sha256=archive_checksum,
        source_size_bytes=record.artifact_size_bytes,
        archive_size_bytes=archive_size,
        row_count=None,
        schema_check_status="not_applicable_file_backed_archive",
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        restore_command=_restore_command(manifest_ref),
        generated_at=generated_at,
        executor_version=EXECUTOR_VERSION,
        dry_run=dry_run,
        mutation_performed=not dry_run,
        sql_mutation_performed=False,
        artifact_index_updated=False,
    )


def _receipt_for_record(
    record: LifecyclePlanRecord,
    *,
    generated_at: str,
    manifest: SqlArchiveManifest | None,
    status: str,
    restore_smoke_status: str,
    reason: str,
    dry_run: bool,
    archive_checksum: str | None,
) -> SqlArchiveReceipt:
    return SqlArchiveReceipt(
        contract_type="archive_receipt" if not dry_run else "archive_receipt_draft",
        receipt_ref=_stable_ref("sql_archive_receipt", record.artifact_id, record.physical_path, status, archive_checksum or ""),
        manifest_ref=manifest.manifest_ref if manifest else None,
        artifact_id=record.artifact_id,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        status=status,
        protected_set_check_status="clear_from_lifecycle_plan",
        restore_smoke_status=restore_smoke_status,
        detach_drop_quarantine_status="not_started",
        source_ref=record.artifact_uri,
        archive_uri=manifest.archive_uri if manifest else None,
        checksum_sha256=archive_checksum,
        row_count=None,
        schema_check_status="not_applicable_file_backed_archive",
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=dry_run,
        mutation_performed=not dry_run and status == "succeeded",
        sql_mutation_performed=False,
        artifact_index_updated=False,
        source_preserved=True,
        reason=reason,
    )


def execute_sql_archive(
    lifecycle_plan: StorageLifecyclePlan,
    *,
    root: Path,
    apply: bool = False,
    overwrite: bool = False,
    generated_at: str | None = None,
) -> SqlArchiveResult:
    """Plan or execute reviewed file-backed archive copies for archive candidates."""

    generated = generated_at or now_utc()
    manifests: list[SqlArchiveManifest] = []
    receipts: list[SqlArchiveReceipt] = []
    restore_receipts: list[SqlArchiveRestoreReceipt] = []
    skipped_records: list[dict[str, Any]] = []

    for record in lifecycle_plan.records:
        if record.protected or record.protected_reason_codes:
            skipped_records.append({
                "artifact_id": record.artifact_id,
                "artifact_uri": record.artifact_uri,
                "physical_path": record.physical_path,
                "plan_action": record.action,
                "skip_reason": "protected_by_lifecycle_plan",
                "protected_reason_codes": tuple(record.protected_reason_codes),
            })
            continue
        if record.action != "archive_candidate":
            skipped_records.append({
                "artifact_id": record.artifact_id,
                "artifact_uri": record.artifact_uri,
                "physical_path": record.physical_path,
                "plan_action": record.action,
                "skip_reason": "not_archive_candidate",
                "protected_reason_codes": tuple(record.protected_reason_codes),
            })
            continue

        if not apply:
            manifest = _manifest_for_record(record, generated_at=generated, dry_run=True, archive_checksum=None, archive_size=None)
            receipt = _receipt_for_record(
                record,
                generated_at=generated,
                manifest=manifest,
                status="planned_not_executed",
                restore_smoke_status="not_performed_dry_run",
                reason="Archive candidate planned only; no archive bytes were written and no SQL mutation was performed.",
                dry_run=True,
                archive_checksum=None,
            )
            manifests.append(manifest)
            receipts.append(receipt)
            restore_receipts.append(_restore_receipt(
                manifest_ref=manifest.manifest_ref,
                artifact_id=record.artifact_id,
                generated_at=generated,
                dry_run=True,
                checksum_status="not_performed_dry_run",
                status="planned_not_executed",
                reason="Restore verification is planned after reviewed archive execution.",
            ))
            continue

        try:
            source = _resolve_repo_file(root, record.physical_path)
            if not source.is_file() or source.is_symlink():
                raise ValueError("archive source must be a regular non-symlink file")
            if record.checksum_sha256 and sha256_file(source) != record.checksum_sha256:
                raise ValueError("source checksum does not match lifecycle-plan checksum")
            archive_path = root / _archive_relative_path(record)
            _gzip_copy(source, archive_path, overwrite=overwrite)
            archive_checksum = sha256_file(archive_path)
            archive_size = archive_path.stat().st_size
            restored_checksum = _sha256_decompressed_gzip(archive_path)
            checksum_status = "passed" if restored_checksum == record.checksum_sha256 else "failed"
            status = "succeeded" if checksum_status == "passed" else "failed_restore_checksum"
            reason = (
                "Reviewed file-backed archive copy written; source preserved; no SQL detach/drop or artifact-index mutation performed."
                if status == "succeeded"
                else "Archive copy was written, but decompressed checksum did not match the lifecycle-plan source checksum."
            )
            manifest = _manifest_for_record(record, generated_at=generated, dry_run=False, archive_checksum=archive_checksum, archive_size=archive_size)
            manifests.append(manifest)
            receipts.append(_receipt_for_record(
                record,
                generated_at=generated,
                manifest=manifest,
                status=status,
                restore_smoke_status=checksum_status,
                reason=reason,
                dry_run=False,
                archive_checksum=archive_checksum,
            ))
            restore_receipts.append(_restore_receipt(
                manifest_ref=manifest.manifest_ref,
                artifact_id=record.artifact_id,
                generated_at=generated,
                dry_run=False,
                checksum_status=checksum_status,
                status=status,
                reason="Archive decompression checksum verification completed without materialized database restore.",
            ))
        except Exception as exc:  # pragma: no cover - exercised through failure receipt tests as needed
            receipt = _receipt_for_record(
                record,
                generated_at=generated,
                manifest=None,
                status="failed",
                restore_smoke_status="not_performed_failure",
                reason=str(exc),
                dry_run=False,
                archive_checksum=None,
            )
            receipts.append(receipt)

    return SqlArchiveResult(
        contract_type="storage_sql_archive_result",
        generated_at=generated,
        source_lifecycle_plan_generated_at=lifecycle_plan.generated_at,
        apply=apply,
        manifests=tuple(manifests),
        receipts=tuple(receipts),
        restore_receipts=tuple(restore_receipts),
        skipped_records=tuple(skipped_records),
    )


def write_sql_archive_result(result: SqlArchiveResult, *, output_path: Path, summary_path: Path | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, result.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, result.summary_json())


def _manifest_from_mapping(row: Mapping[str, Any]) -> SqlArchiveManifest:
    return SqlArchiveManifest(**dict(row))


def load_sql_archive_result_json(path: Path) -> SqlArchiveResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("SQL archive result must be a JSON object")
    manifests = tuple(_manifest_from_mapping(row) for row in data.get("manifests", []) if isinstance(row, Mapping))
    receipts = tuple(SqlArchiveReceipt(**dict(row)) for row in data.get("receipts", []) if isinstance(row, Mapping))
    restore_receipts = tuple(SqlArchiveRestoreReceipt(**dict(row)) for row in data.get("restore_receipts", []) if isinstance(row, Mapping))
    skipped = tuple(dict(row) for row in data.get("skipped_records", []) if isinstance(row, Mapping))
    return SqlArchiveResult(
        contract_type=str(data.get("contract_type", "storage_sql_archive_result")),
        generated_at=str(data.get("generated_at", "")),
        source_lifecycle_plan_generated_at=data.get("source_lifecycle_plan_generated_at"),
        apply=bool(data.get("apply", False)),
        manifests=manifests,
        receipts=receipts,
        restore_receipts=restore_receipts,
        skipped_records=skipped,
    )


def verify_sql_archive_restore(
    archive_result: SqlArchiveResult,
    *,
    root: Path,
    manifest_ref: str | None = None,
    generated_at: str | None = None,
) -> SqlArchiveRestoreVerification:
    """Verify existing gzip archive copies without materializing a database restore."""

    generated = generated_at or now_utc()
    receipts: list[SqlArchiveRestoreReceipt] = []
    skipped_records: list[dict[str, Any]] = []
    for manifest in archive_result.manifests:
        if manifest_ref and manifest.manifest_ref != manifest_ref:
            skipped_records.append({"manifest_ref": manifest.manifest_ref, "skip_reason": "manifest_ref_filter"})
            continue
        if not manifest.archive_checksum_sha256:
            receipts.append(_restore_receipt(
                manifest_ref=manifest.manifest_ref,
                artifact_id=manifest.artifact_id,
                generated_at=generated,
                dry_run=True,
                checksum_status="not_performed_missing_archive_checksum",
                status="planned_not_executed",
                reason="Manifest has no executed archive checksum; restore verification remains planned only.",
            ))
            continue
        try:
            archive_path = _resolve_repo_file(root, manifest.archive_path)
            if sha256_file(archive_path) != manifest.archive_checksum_sha256:
                checksum_status = "failed_archive_checksum"
                status = "failed"
                reason = "Archive file checksum does not match manifest archive checksum."
            else:
                restored_checksum = _sha256_decompressed_gzip(archive_path)
                checksum_status = "passed" if restored_checksum == manifest.source_checksum_sha256 else "failed_source_checksum"
                status = "succeeded" if checksum_status == "passed" else "failed"
                reason = "Archive decompression checksum verification completed without database restore."
            receipts.append(_restore_receipt(
                manifest_ref=manifest.manifest_ref,
                artifact_id=manifest.artifact_id,
                generated_at=generated,
                dry_run=False,
                checksum_status=checksum_status,
                status=status,
                reason=reason,
            ))
        except Exception as exc:
            receipts.append(_restore_receipt(
                manifest_ref=manifest.manifest_ref,
                artifact_id=manifest.artifact_id,
                generated_at=generated,
                dry_run=False,
                checksum_status="failed_exception",
                status="failed",
                reason=str(exc),
            ))
    return SqlArchiveRestoreVerification(
        contract_type="storage_sql_archive_restore_verification",
        generated_at=generated,
        source_archive_result_generated_at=archive_result.generated_at,
        receipts=tuple(receipts),
        skipped_records=tuple(skipped_records),
    )


def write_sql_archive_restore_verification(verification: SqlArchiveRestoreVerification, *, output_path: Path, summary_path: Path | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, verification.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, verification.summary_json())


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


def parse_archive_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or execute reviewed file-backed SQL archive copies for lifecycle archive candidates.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--lifecycle-plan-json", help="Existing lifecycle-plan JSON path. Default builds a live dry-run plan.")
    parser.add_argument("--index-jsonl", help="Existing artifact-index JSONL path used when building a plan.")
    parser.add_argument("--protected-set-json", help="Protected-set JSON path used when building a plan.")
    parser.add_argument("--policy-file", help="JSON lifecycle policy file used when building a plan.")
    parser.add_argument("--include-root", action="append", dest="include_roots", help="Relative root/file for live artifact-index scan. Ignored when --lifecycle-plan-json or --index-jsonl is used.")
    parser.add_argument("--apply-reviewed-archive", action="store_true", help="Write reviewed gzip archive copies. Default is dry-run planning only.")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing archive outputs in apply mode.")
    parser.add_argument("--write", action="store_true", help="Write result JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_SQL_ARCHIVE_OUTPUT), help="Relative/absolute result JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_SQL_ARCHIVE_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full result JSON instead of summary JSON.")
    return parser.parse_args(argv)


def archive_main(argv: Sequence[str] | None = None) -> int:
    args = parse_archive_args(argv)
    root = Path(args.root).resolve()
    plan = _build_or_load_lifecycle_plan(args, root)
    result = execute_sql_archive(plan, root=root, apply=args.apply_reviewed_archive, overwrite=args.overwrite)
    if args.write:
        write_sql_archive_result(result, output_path=_resolve_path(root, Path(args.output_path)), summary_path=_resolve_path(root, Path(args.summary_path)))
    print(result.to_json() if args.json else result.summary_json(), end="")
    return 0


def parse_restore_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify reviewed file-backed SQL archive gzip copies without materialized database restore.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--archive-result-json", default=str(DEFAULT_SQL_ARCHIVE_OUTPUT), help="Archive result JSON path containing executed manifests.")
    parser.add_argument("--manifest-ref", help="Optional manifest_ref filter.")
    parser.add_argument("--write", action="store_true", help="Write verification JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_SQL_ARCHIVE_RESTORE_OUTPUT), help="Relative/absolute verification JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_SQL_ARCHIVE_RESTORE_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full verification JSON instead of summary JSON.")
    return parser.parse_args(argv)


def restore_main(argv: Sequence[str] | None = None) -> int:
    args = parse_restore_args(argv)
    root = Path(args.root).resolve()
    archive_result = load_sql_archive_result_json(_resolve_path(root, Path(args.archive_result_json)))
    verification = verify_sql_archive_restore(archive_result, root=root, manifest_ref=args.manifest_ref)
    if args.write:
        write_sql_archive_restore_verification(verification, output_path=_resolve_path(root, Path(args.output_path)), summary_path=_resolve_path(root, Path(args.summary_path)))
    print(verification.to_json() if args.json else verification.summary_json(), end="")
    return 0
