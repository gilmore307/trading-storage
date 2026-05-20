"""Reviewed quarantine/delete executor receipt builder.

This is a safety-first executable surface for the lifecycle phase after
quarantine/recheck evidence.  The current implementation never moves or deletes
payloads: it validates gate evidence and emits explicit blocked/planned receipts.
Physical quarantine moves and deletions remain disabled until a separate reviewed
approval and implementation slice exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading_storage.artifact_index import now_utc
from trading_storage.io import write_text_atomic
from trading_storage.quarantine_recheck import QuarantineRecheckEvidence, QuarantineRecheckRecord

DEFAULT_QUARANTINE_DELETE_OUTPUT = Path("storage/90_lifecycle/execution/quarantine_delete_result.json")
DEFAULT_QUARANTINE_DELETE_SUMMARY_OUTPUT = Path("storage/90_lifecycle/execution/quarantine_delete_summary.json")
EXECUTOR_VERSION = "storage_quarantine_delete_executor_v0_1"


@dataclass(frozen=True)
class QuarantineReceipt:
    """Receipt for a planned or blocked quarantine move."""

    contract_type: str
    receipt_ref: str
    artifact_id: str
    policy_id: str | None
    rule_id: str | None
    status: str
    source_uri: str
    source_path: str
    quarantine_uri: str | None
    quarantine_path: str | None
    initial_check_status: str
    final_recheck_status: str
    executor_version: str
    generated_at: str
    dry_run: bool
    mutation_performed: bool
    quarantine_move_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeletionReceipt:
    """Receipt for a planned or blocked deletion attempt."""

    contract_type: str
    receipt_ref: str
    artifact_id: str
    policy_id: str | None
    rule_id: str | None
    status: str
    source_uri: str
    source_path: str
    quarantine_ref: str | None
    tombstone_ref: str | None
    initial_check_status: str
    final_recheck_status: str
    executor_version: str
    generated_at: str
    dry_run: bool
    mutation_performed: bool
    delete_performed: bool
    artifact_index_updated: bool
    sql_mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactTombstoneDraft:
    """Draft tombstone metadata for a future deletion executor."""

    contract_type: str
    tombstone_ref: str
    artifact_id: str
    previous_uri: str
    previous_path: str
    deletion_receipt_ref: str
    policy_id: str | None
    rule_id: str | None
    restore_possible: bool
    restore_manifest_ref: str | None
    generated_at: str
    executor_version: str
    dry_run: bool
    mutation_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuarantineDeleteResult:
    """Result bundle for reviewed quarantine/delete gate execution."""

    contract_type: str
    generated_at: str
    source_quarantine_recheck_generated_at: str | None
    quarantine_receipts: tuple[QuarantineReceipt, ...]
    deletion_receipts: tuple[DeletionReceipt, ...]
    tombstone_drafts: tuple[ArtifactTombstoneDraft, ...]
    skipped_records: tuple[dict[str, Any], ...]

    @property
    def summary(self) -> dict[str, Any]:
        quarantine_status_counts: dict[str, int] = {}
        deletion_status_counts: dict[str, int] = {}
        skipped_counts: dict[str, int] = {}
        for receipt in self.quarantine_receipts:
            quarantine_status_counts[receipt.status] = quarantine_status_counts.get(receipt.status, 0) + 1
        for receipt in self.deletion_receipts:
            deletion_status_counts[receipt.status] = deletion_status_counts.get(receipt.status, 0) + 1
        for row in self.skipped_records:
            reason = str(row.get("skip_reason", "unknown"))
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
        return {
            "contract_type": "storage_quarantine_delete_summary",
            "generated_at": self.generated_at,
            "source_quarantine_recheck_generated_at": self.source_quarantine_recheck_generated_at,
            "quarantine_receipt_count": len(self.quarantine_receipts),
            "deletion_receipt_count": len(self.deletion_receipts),
            "tombstone_draft_count": len(self.tombstone_drafts),
            "skipped_record_count": len(self.skipped_records),
            "quarantine_status_counts": dict(sorted(quarantine_status_counts.items())),
            "deletion_status_counts": dict(sorted(deletion_status_counts.items())),
            "skipped_reason_counts": dict(sorted(skipped_counts.items())),
            "mutation_performed": False,
            "quarantine_move_performed": False,
            "delete_performed": False,
            "artifact_index_updated": False,
            "sql_mutation_performed": False,
            "executor_mode": "gate_receipts_only_no_payload_mutation",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "source_quarantine_recheck_generated_at": self.source_quarantine_recheck_generated_at,
            "summary": self.summary,
            "quarantine_receipts": [row.to_dict() for row in self.quarantine_receipts],
            "deletion_receipts": [row.to_dict() for row in self.deletion_receipts],
            "tombstone_drafts": [row.to_dict() for row in self.tombstone_drafts],
            "skipped_records": list(self.skipped_records),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _stable_ref(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _quarantine_path(record: QuarantineRecheckRecord) -> str:
    return f"storage/90_lifecycle/quarantine/{record.artifact_id}/{Path(record.physical_path).name}"


def _quarantine_uri(record: QuarantineRecheckRecord) -> str:
    return "storage://trading-storage/" + _quarantine_path(record)


def _quarantine_receipt(record: QuarantineRecheckRecord, *, generated_at: str, status: str, reason: str) -> QuarantineReceipt:
    allowed_to_plan = status == "planned_not_executed"
    return QuarantineReceipt(
        contract_type="quarantine_receipt_draft",
        receipt_ref=_stable_ref("quarantine_receipt", record.artifact_id, record.physical_path, status),
        artifact_id=record.artifact_id,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        status=status,
        source_uri=record.artifact_uri,
        source_path=record.physical_path,
        quarantine_uri=_quarantine_uri(record) if allowed_to_plan else None,
        quarantine_path=_quarantine_path(record) if allowed_to_plan else None,
        initial_check_status=record.initial_check_status,
        final_recheck_status=record.recheck_status,
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=True,
        mutation_performed=False,
        quarantine_move_performed=False,
        reason=reason,
    )


def _deletion_receipt(
    record: QuarantineRecheckRecord,
    *,
    generated_at: str,
    status: str,
    quarantine_ref: str | None,
    tombstone_ref: str | None,
    reason: str,
) -> DeletionReceipt:
    return DeletionReceipt(
        contract_type="deletion_receipt_draft",
        receipt_ref=_stable_ref("deletion_receipt", record.artifact_id, record.physical_path, status),
        artifact_id=record.artifact_id,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        status=status,
        source_uri=record.artifact_uri,
        source_path=record.physical_path,
        quarantine_ref=quarantine_ref,
        tombstone_ref=tombstone_ref,
        initial_check_status=record.initial_check_status,
        final_recheck_status=record.recheck_status,
        executor_version=EXECUTOR_VERSION,
        generated_at=generated_at,
        dry_run=True,
        mutation_performed=False,
        delete_performed=False,
        artifact_index_updated=False,
        sql_mutation_performed=False,
        reason=reason,
    )


def _tombstone_draft(record: QuarantineRecheckRecord, *, generated_at: str, deletion_receipt_ref: str) -> ArtifactTombstoneDraft:
    return ArtifactTombstoneDraft(
        contract_type="artifact_tombstone_draft",
        tombstone_ref=_stable_ref("artifact_tombstone", record.artifact_id, record.physical_path),
        artifact_id=record.artifact_id,
        previous_uri=record.artifact_uri,
        previous_path=record.physical_path,
        deletion_receipt_ref=deletion_receipt_ref,
        policy_id=record.policy_id,
        rule_id=record.rule_id,
        restore_possible=False,
        restore_manifest_ref=None,
        generated_at=generated_at,
        executor_version=EXECUTOR_VERSION,
        dry_run=True,
        mutation_performed=False,
    )


def build_quarantine_delete_result(evidence: QuarantineRecheckEvidence, *, generated_at: str | None = None) -> QuarantineDeleteResult:
    """Validate quarantine/delete gates and emit no-mutation receipts/drafts."""

    generated = generated_at or now_utc()
    quarantine_receipts: list[QuarantineReceipt] = []
    deletion_receipts: list[DeletionReceipt] = []
    tombstone_drafts: list[ArtifactTombstoneDraft] = []
    skipped_records: list[dict[str, Any]] = []

    for record in evidence.records:
        if not record.quarantine_candidate:
            skipped_records.append({
                "artifact_id": record.artifact_id,
                "artifact_uri": record.artifact_uri,
                "physical_path": record.physical_path,
                "plan_action": record.plan_action,
                "skip_reason": "not_quarantine_candidate",
                "initial_check_status": record.initial_check_status,
                "recheck_status": record.recheck_status,
            })
            continue
        if record.initial_check_status != "clear":
            quarantine_receipts.append(_quarantine_receipt(record, generated_at=generated, status="blocked_initial_check", reason="Initial protected-set check is not clear."))
            deletion_receipts.append(_deletion_receipt(record, generated_at=generated, status="blocked_initial_check", quarantine_ref=None, tombstone_ref=None, reason="Deletion blocked by initial protected-set check."))
            continue
        if record.recheck_status != "clear":
            quarantine_receipts.append(_quarantine_receipt(record, generated_at=generated, status="blocked_final_recheck", reason="Final protected-set recheck is not clear or not performed."))
            deletion_receipts.append(_deletion_receipt(record, generated_at=generated, status="blocked_final_recheck", quarantine_ref=None, tombstone_ref=None, reason="Deletion blocked until final protected-set recheck is clear."))
            continue

        quarantine = _quarantine_receipt(record, generated_at=generated, status="planned_not_executed", reason="Quarantine move is gate-clear but physical moves remain disabled in this slice.")
        deletion = _deletion_receipt(
            record,
            generated_at=generated,
            status="planned_not_executed",
            quarantine_ref=quarantine.receipt_ref,
            tombstone_ref=None,
            reason="Deletion is gate-clear but physical deletion remains disabled pending a separately approved mutation executor.",
        )
        tombstone = _tombstone_draft(record, generated_at=generated, deletion_receipt_ref=deletion.receipt_ref)
        deletion = _deletion_receipt(
            record,
            generated_at=generated,
            status="planned_not_executed",
            quarantine_ref=quarantine.receipt_ref,
            tombstone_ref=tombstone.tombstone_ref,
            reason="Deletion is gate-clear but physical deletion remains disabled pending a separately approved mutation executor.",
        )
        quarantine_receipts.append(quarantine)
        deletion_receipts.append(deletion)
        tombstone_drafts.append(tombstone)

    return QuarantineDeleteResult(
        contract_type="storage_quarantine_delete_result",
        generated_at=generated,
        source_quarantine_recheck_generated_at=evidence.generated_at,
        quarantine_receipts=tuple(quarantine_receipts),
        deletion_receipts=tuple(deletion_receipts),
        tombstone_drafts=tuple(tombstone_drafts),
        skipped_records=tuple(skipped_records),
    )


def _record_from_mapping(row: Mapping[str, Any]) -> QuarantineRecheckRecord:
    values = dict(row)
    for key in ("initial_protected_reason_codes", "final_protected_reason_codes"):
        values[key] = tuple(values.get(key, ()))
    return QuarantineRecheckRecord(**values)


def load_quarantine_recheck_evidence_json(path: Path) -> QuarantineRecheckEvidence:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("quarantine/recheck evidence must be a JSON object")
    records = tuple(_record_from_mapping(row) for row in data.get("records", []) if isinstance(row, Mapping))
    return QuarantineRecheckEvidence(
        contract_type=str(data.get("contract_type", "storage_quarantine_recheck_evidence")),
        generated_at=str(data.get("generated_at", "")),
        source_lifecycle_plan_generated_at=data.get("source_lifecycle_plan_generated_at"),
        final_protected_set_generated_at=data.get("final_protected_set_generated_at"),
        records=records,
    )


def write_quarantine_delete_result(result: QuarantineDeleteResult, *, output_path: Path, summary_path: Path | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, result.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, result.summary_json())


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build reviewed no-mutation quarantine/delete gate receipts from quarantine/recheck evidence.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--quarantine-recheck-json", default="storage/90_lifecycle/quarantine_recheck/quarantine_recheck_evidence.json", help="Quarantine/recheck evidence JSON path.")
    parser.add_argument("--write", action="store_true", help="Write result JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_QUARANTINE_DELETE_OUTPUT), help="Relative/absolute result JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_QUARANTINE_DELETE_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full result JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    evidence = load_quarantine_recheck_evidence_json(_resolve_path(root, Path(args.quarantine_recheck_json)))
    result = build_quarantine_delete_result(evidence)
    if args.write:
        write_quarantine_delete_result(result, output_path=_resolve_path(root, Path(args.output_path)), summary_path=_resolve_path(root, Path(args.summary_path)))
    print(result.to_json() if args.json else result.summary_json(), end="")
    return 0
