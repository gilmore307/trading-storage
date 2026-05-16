"""Safe single-file compression executor for storage lifecycle candidates.

This is the first intentionally narrow mutating lifecycle executor.  It only
handles unprotected `compress_candidate` file rows.  In apply mode it writes a
zstd compressed copy, verifies a decompression checksum smoke test, writes
receipt evidence, and preserves the original file.  It never deletes originals,
updates the artifact index, quarantines files, detaches/drops SQL, or handles
directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from trading_storage.artifact_index import ArtifactIndex, ArtifactIndexRecord, build_artifact_index, now_utc, sha256_file
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

DEFAULT_SINGLE_FILE_COMPRESSION_OUTPUT = Path("storage/lifecycle_execution/single_file_compression_result.json")
DEFAULT_SINGLE_FILE_COMPRESSION_SUMMARY_OUTPUT = Path("storage/lifecycle_execution/single_file_compression_summary.json")
EXECUTOR_VERSION = "storage_single_file_compression_executor_v0_1"


@dataclass(frozen=True)
class CompressionManifest:
    """Manifest for a planned or executed single-file compression copy."""

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
    original_preserved: bool
    delete_original_performed: bool
    artifact_index_updated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompressionReceipt:
    """Receipt for a planned, successful, skipped, or failed compression attempt."""

    contract_type: str
    receipt_ref: str
    manifest_ref: str | None
    artifact_id: str
    policy_id: str | None
    rule_id: str | None
    status: str
    protected_set_check_status: str
    restore_smoke_status: str
    original_uri: str
    compressed_uri: str | None
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
    original_preserved: bool
    delete_original_performed: bool
    artifact_index_updated: bool
    sql_mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreVerificationReceipt:
    """Receipt for zstd decompression checksum verification."""

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
class SingleFileCompressionResult:
    """Result bundle for the safe single-file compression executor."""

    contract_type: str
    generated_at: str
    source_lifecycle_plan_generated_at: str | None
    apply: bool
    manifests: tuple[CompressionManifest, ...]
    receipts: tuple[CompressionReceipt, ...]
    restore_receipts: tuple[RestoreVerificationReceipt, ...]
    skipped_records: tuple[dict[str, Any], ...]

    @property
    def summary(self) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        skipped_counts: dict[str, int] = {}
        mutation_count = 0
        for receipt in self.receipts:
            status_counts[receipt.status] = status_counts.get(receipt.status, 0) + 1
            if receipt.mutation_performed:
                mutation_count += 1
        for row in self.skipped_records:
            reason = str(row.get("skip_reason", "unknown"))
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
        return {
            "contract_type": "storage_single_file_compression_summary_v1",
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
            "delete_original_performed": False,
            "artifact_index_updated": False,
            "sql_mutation_performed": False,
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


def _stable_ref(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _compressed_relative_path(record: LifecyclePlanRecord) -> Path:
    return Path("storage") / "archive" / "compressed" / record.artifact_id / (Path(record.physical_path).name + ".zst")


def _compressed_uri(record: LifecyclePlanRecord) -> str:
    return "storage://trading-storage/" + str(_compressed_relative_path(record)).replace("\\", "/")


def _restore_command(manifest_ref: str) -> str:
    return f"PYTHONPATH=src python3 scripts/lifecycle/verify_single_file_compression_restore.py --manifest-ref {manifest_ref}"


def _resolve_repo_file(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe artifact path: {relative_path!r}")
    resolved = (root / path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError(f"artifact path escapes root: {relative_path!r}")
    return resolved


def _run_zstd_compress(source: Path, destination: Path, *, overwrite: bool) -> None:
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd command not found; cannot apply compression")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [zstd, "-q", "-f" if overwrite else "--no-progress", "-o", str(destination), str(source)]
    if not overwrite:
        command = [zstd, "-q", "-o", str(destination), str(source)]
    subprocess.run(command, check=True)


def _sha256_decompressed_zstd(path: Path) -> str:
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd command not found; cannot verify restore smoke")
    process = subprocess.Popen([zstd, "-q", "-dc", str(path)], stdout=subprocess.PIPE)
    assert process.stdout is not None
    digest = hashlib.sha256()
    with process.stdout:
        for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
            digest.update(chunk)
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"zstd restore smoke failed with exit code {return_code}")
    return "sha256:" + digest.hexdigest()


def _manifest_for_record(
    record: LifecyclePlanRecord,
    *,
    generated_at: str,
    dry_run: bool,
    mutation_performed: bool,
    compressed_size_bytes: int | None,
    compressed_checksum_sha256: str | None,
) -> CompressionManifest:
    manifest_ref = _stable_ref("compression_manifest", record.artifact_id, record.physical_path, record.rule_id)
    compressed_relative = _compressed_relative_path(record)
    return CompressionManifest(
        contract_type="compression_manifest_v1",
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        artifact_kind=record.artifact_kind,
        original_uri=record.artifact_uri,
        original_path=record.physical_path,
        compressed_uri=_compressed_uri(record),
        compressed_path=str(compressed_relative).replace("\\", "/"),
        codec="zstd",
        read_mode="restore_required",
        original_size_bytes=record.artifact_size_bytes,
        compressed_size_bytes=compressed_size_bytes,
        original_checksum_sha256=record.checksum_sha256,
        compressed_checksum_sha256=compressed_checksum_sha256,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        restore_command=_restore_command(manifest_ref),
        generated_at=generated_at,
        executor_version=EXECUTOR_VERSION,
        dry_run=dry_run,
        mutation_performed=mutation_performed,
        original_preserved=True,
        delete_original_performed=False,
        artifact_index_updated=False,
    )


def _receipt_for_record(
    record: LifecyclePlanRecord,
    *,
    generated_at: str,
    manifest_ref: str | None,
    status: str,
    dry_run: bool,
    mutation_performed: bool,
    compressed_size_bytes: int | None,
    compressed_checksum_sha256: str | None,
    restore_smoke_status: str,
    reason: str,
) -> CompressionReceipt:
    return CompressionReceipt(
        contract_type="compression_receipt_v1",
        receipt_ref=_stable_ref("compression_receipt", manifest_ref or "no_manifest", record.artifact_id, status),
        manifest_ref=manifest_ref,
        artifact_id=record.artifact_id,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        status=status,
        protected_set_check_status="clear_from_lifecycle_plan" if not record.protected_reason_codes else "blocked",
        restore_smoke_status=restore_smoke_status,
        original_uri=record.artifact_uri,
        compressed_uri=_compressed_uri(record) if manifest_ref else None,
        codec="zstd",
        read_mode="restore_required",
        original_size_bytes=record.artifact_size_bytes,
        compressed_size_bytes=compressed_size_bytes,
        original_checksum_sha256=record.checksum_sha256,
        compressed_checksum_sha256=compressed_checksum_sha256,
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=dry_run,
        mutation_performed=mutation_performed,
        original_preserved=True,
        delete_original_performed=False,
        artifact_index_updated=False,
        sql_mutation_performed=False,
        reason=reason,
    )


def _restore_receipt(
    record: LifecyclePlanRecord,
    *,
    generated_at: str,
    manifest_ref: str,
    dry_run: bool,
    mutation_performed: bool,
    checksum_status: str,
    status: str,
    reason: str,
) -> RestoreVerificationReceipt:
    return RestoreVerificationReceipt(
        contract_type="restore_receipt_v1",
        receipt_ref=_stable_ref("restore_receipt", manifest_ref, record.artifact_id, checksum_status),
        source_manifest_ref=manifest_ref,
        source_artifact_id=record.artifact_id,
        restore_mode="verification_only",
        restore_destination=f"storage/restore_smoke/compression/{record.artifact_id}",
        checksum_status=checksum_status,
        schema_check_status="not_applicable",
        row_count_check_status="not_applicable",
        status=status,
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=dry_run,
        mutation_performed=mutation_performed,
        reason=reason,
    )


def _skip(record: LifecyclePlanRecord, reason: str) -> dict[str, Any]:
    return {
        "artifact_id": record.artifact_id,
        "artifact_uri": record.artifact_uri,
        "physical_path": record.physical_path,
        "plan_action": record.action,
        "skip_reason": reason,
        "protected_reason_codes": tuple(record.protected_reason_codes),
    }


def execute_single_file_compression(
    lifecycle_plan: StorageLifecyclePlan,
    *,
    root: Path = Path("."),
    apply: bool = False,
    overwrite: bool = False,
    generated_at: str | None = None,
) -> SingleFileCompressionResult:
    """Execute or dry-run the narrow single-file compression slice."""

    root = root.resolve()
    generated = generated_at or now_utc()
    manifests: list[CompressionManifest] = []
    receipts: list[CompressionReceipt] = []
    restore_receipts: list[RestoreVerificationReceipt] = []
    skipped_records: list[dict[str, Any]] = []

    for record in lifecycle_plan.records:
        if record.protected or record.protected_reason_codes:
            skipped_records.append(_skip(record, "protected_by_lifecycle_plan"))
            continue
        if record.action != "compress_candidate":
            skipped_records.append(_skip(record, "not_compress_candidate"))
            continue
        try:
            source = _resolve_repo_file(root, record.physical_path)
            destination = _resolve_repo_file(root, str(_compressed_relative_path(record)))
        except ValueError as exc:
            skipped_records.append(_skip(record, str(exc)))
            continue
        if not source.exists() or not source.is_file() or source.is_symlink():
            skipped_records.append(_skip(record, "source_missing_not_file_or_symlink"))
            continue
        if destination.exists() and not overwrite:
            skipped_records.append(_skip(record, "compressed_path_exists"))
            continue

        current_original_checksum = sha256_file(source)
        if record.checksum_sha256 and current_original_checksum != record.checksum_sha256:
            skipped_records.append(_skip(record, "source_checksum_mismatch"))
            continue

        manifest_ref = _stable_ref("compression_manifest", record.artifact_id, record.physical_path, record.rule_id)
        if not apply:
            manifest = _manifest_for_record(
                record,
                generated_at=generated,
                dry_run=True,
                mutation_performed=False,
                compressed_size_bytes=None,
                compressed_checksum_sha256=None,
            )
            manifests.append(manifest)
            receipts.append(
                _receipt_for_record(
                    record,
                    generated_at=generated,
                    manifest_ref=manifest.manifest_ref,
                    status="planned_not_executed",
                    dry_run=True,
                    mutation_performed=False,
                    compressed_size_bytes=None,
                    compressed_checksum_sha256=None,
                    restore_smoke_status="not_performed_dry_run",
                    reason="Dry-run only; no compressed copy was written.",
                )
            )
            restore_receipts.append(
                _restore_receipt(
                    record,
                    generated_at=generated,
                    manifest_ref=manifest.manifest_ref,
                    dry_run=True,
                    mutation_performed=False,
                    checksum_status="not_performed_dry_run",
                    status="planned_not_executed",
                    reason="Dry-run only; decompression checksum smoke was not performed.",
                )
            )
            continue

        try:
            _run_zstd_compress(source, destination, overwrite=overwrite)
            compressed_checksum = sha256_file(destination)
            restored_checksum = _sha256_decompressed_zstd(destination)
            checksum_status = "match" if restored_checksum == current_original_checksum else "mismatch"
            status = "succeeded" if checksum_status == "match" else "failed_restore_checksum_mismatch"
            compressed_size = destination.stat().st_size
            manifest = _manifest_for_record(
                record,
                generated_at=generated,
                dry_run=False,
                mutation_performed=True,
                compressed_size_bytes=compressed_size,
                compressed_checksum_sha256=compressed_checksum,
            )
            manifests.append(manifest)
            receipts.append(
                _receipt_for_record(
                    record,
                    generated_at=generated,
                    manifest_ref=manifest_ref,
                    status=status,
                    dry_run=False,
                    mutation_performed=True,
                    compressed_size_bytes=compressed_size,
                    compressed_checksum_sha256=compressed_checksum,
                    restore_smoke_status=checksum_status,
                    reason="Compressed copy written and original preserved." if status == "succeeded" else "Compressed copy written but restore checksum smoke failed; original preserved.",
                )
            )
            restore_receipts.append(
                _restore_receipt(
                    record,
                    generated_at=generated,
                    manifest_ref=manifest_ref,
                    dry_run=False,
                    mutation_performed=True,
                    checksum_status=checksum_status,
                    status="succeeded" if checksum_status == "match" else "failed",
                    reason="Decompressed bytes matched original checksum." if checksum_status == "match" else "Decompressed bytes did not match original checksum.",
                )
            )
        except Exception as exc:  # noqa: BLE001 - receipt must capture failed executor attempts
            receipts.append(
                _receipt_for_record(
                    record,
                    generated_at=generated,
                    manifest_ref=None,
                    status="failed",
                    dry_run=False,
                    mutation_performed=False,
                    compressed_size_bytes=None,
                    compressed_checksum_sha256=None,
                    restore_smoke_status="not_performed_failed_before_verify",
                    reason=f"Compression executor failed before verified output: {exc}",
                )
            )

    return SingleFileCompressionResult(
        contract_type="storage_single_file_compression_result_v1",
        generated_at=generated,
        source_lifecycle_plan_generated_at=lifecycle_plan.generated_at,
        apply=apply,
        manifests=tuple(manifests),
        receipts=tuple(receipts),
        restore_receipts=tuple(restore_receipts),
        skipped_records=tuple(skipped_records),
    )


def write_single_file_compression_result(
    result: SingleFileCompressionResult,
    *,
    output_path: Path,
    summary_path: Path | None = None,
) -> None:
    """Write compression result JSON and optional summary JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.to_json(), encoding="utf-8")
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(result.summary_json(), encoding="utf-8")


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _build_or_load_lifecycle_plan(args: argparse.Namespace, root: Path) -> StorageLifecyclePlan:
    if args.lifecycle_plan_json:
        return load_storage_lifecycle_plan_json(_resolve_path(root, Path(args.lifecycle_plan_json)))
    if args.index_jsonl:
        index_or_records: ArtifactIndex | Sequence[ArtifactIndexRecord] = load_artifact_index_jsonl(_resolve_path(root, Path(args.index_jsonl)))
    else:
        index_or_records = build_artifact_index(root=root, include_roots=tuple(args.include_roots or ("storage/artifacts",)))
    protected_set = load_protected_set_json(_resolve_path(root, Path(args.protected_set_json))) if args.protected_set_json else None
    rules = load_policy_rules(_resolve_path(root, Path(args.policy_file))) if args.policy_file else DEFAULT_POLICY_RULES
    return plan_storage_lifecycle(index_or_records, protected_set=protected_set, rules=rules)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely compress unprotected single-file lifecycle candidates.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--lifecycle-plan-json", help="Existing lifecycle-plan JSON path. Default builds a live dry-run plan.")
    parser.add_argument("--index-jsonl", help="Existing artifact-index JSONL path used when building a plan.")
    parser.add_argument("--protected-set-json", help="Protected-set JSON path used when building a plan.")
    parser.add_argument("--policy-file", help="JSON lifecycle policy file used when building a plan.")
    parser.add_argument("--include-root", action="append", dest="include_roots", help="Relative root/file for live artifact-index scan. Ignored when --lifecycle-plan-json or --index-jsonl is used.")
    parser.add_argument("--apply", action="store_true", help="Write compressed copies for eligible candidates. Default is dry-run only.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing compressed copy. Default refuses existing outputs.")
    parser.add_argument("--write", action="store_true", help="Write result JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_SINGLE_FILE_COMPRESSION_OUTPUT), help="Relative/absolute result JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_SINGLE_FILE_COMPRESSION_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full result JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    plan = _build_or_load_lifecycle_plan(args, root)
    result = execute_single_file_compression(plan, root=root, apply=args.apply, overwrite=args.overwrite)
    if args.write:
        write_single_file_compression_result(
            result,
            output_path=_resolve_path(root, Path(args.output_path)),
            summary_path=_resolve_path(root, Path(args.summary_path)),
        )
    if args.json:
        print(result.to_json(), end="")
    else:
        print(result.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
