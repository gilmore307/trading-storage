"""Dry-run quarantine/recheck evidence for storage lifecycle candidates.

This module is the safety-evidence slice before any deletion executor exists. It
consumes a dry-run lifecycle plan plus optional final protected-set evidence and
reports whether quarantine candidates are blocked, still pending recheck, or
clear on recheck. It never moves, quarantines, deletes, detaches SQL, or emits a
successful deletion authorization.
"""

from __future__ import annotations

import argparse
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
from trading_storage.protected_set import ProtectedSet, load_artifact_index_jsonl

DEFAULT_QUARANTINE_RECHECK_OUTPUT = Path("storage/90_lifecycle/quarantine_recheck/quarantine_recheck_evidence.json")
DEFAULT_QUARANTINE_RECHECK_SUMMARY_OUTPUT = Path("storage/90_lifecycle/quarantine_recheck/quarantine_recheck_summary.json")


@dataclass(frozen=True)
class QuarantineRecheckRecord:
    """One dry-run quarantine/recheck evidence row."""

    artifact_id: str
    artifact_kind: str
    artifact_uri: str
    physical_path: str
    plan_action: str
    policy_id: str | None
    rule_id: str | None
    initial_protected: bool
    initial_protected_reason_codes: tuple[str, ...]
    initial_check_status: str
    quarantine_candidate: bool
    quarantine_state: str
    recheck_required: bool
    recheck_status: str
    final_protected_reason_codes: tuple[str, ...]
    deletion_allowed: bool
    mutation_performed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuarantineRecheckEvidence:
    """Dry-run evidence for quarantine-before-delete safety gates."""

    contract_type: str
    generated_at: str
    source_lifecycle_plan_generated_at: str | None
    final_protected_set_generated_at: str | None
    records: tuple[QuarantineRecheckRecord, ...]

    @property
    def summary(self) -> dict[str, Any]:
        state_counts: dict[str, int] = {}
        recheck_counts: dict[str, int] = {}
        quarantine_candidate_count = 0
        initial_clear_candidate_count = 0
        blocked_initial_count = 0
        final_recheck_clear_count = 0
        final_recheck_blocked_count = 0
        deletion_allowed_count = 0
        for record in self.records:
            state_counts[record.quarantine_state] = state_counts.get(record.quarantine_state, 0) + 1
            recheck_counts[record.recheck_status] = recheck_counts.get(record.recheck_status, 0) + 1
            if record.quarantine_candidate:
                quarantine_candidate_count += 1
            if record.initial_check_status == "clear" and record.quarantine_candidate:
                initial_clear_candidate_count += 1
            if record.initial_check_status == "blocked":
                blocked_initial_count += 1
            if record.recheck_status == "clear":
                final_recheck_clear_count += 1
            if record.recheck_status == "blocked":
                final_recheck_blocked_count += 1
            if record.deletion_allowed:
                deletion_allowed_count += 1
        return {
            "contract_type": "storage_quarantine_recheck_summary",
            "generated_at": self.generated_at,
            "source_lifecycle_plan_generated_at": self.source_lifecycle_plan_generated_at,
            "final_protected_set_generated_at": self.final_protected_set_generated_at,
            "record_count": len(self.records),
            "quarantine_candidate_count": quarantine_candidate_count,
            "initial_clear_candidate_count": initial_clear_candidate_count,
            "blocked_initial_count": blocked_initial_count,
            "final_recheck_clear_count": final_recheck_clear_count,
            "final_recheck_blocked_count": final_recheck_blocked_count,
            "deletion_allowed_count": deletion_allowed_count,
            "mutation_performed": False,
            "state_counts": dict(sorted(state_counts.items())),
            "recheck_status_counts": dict(sorted(recheck_counts.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "source_lifecycle_plan_generated_at": self.source_lifecycle_plan_generated_at,
            "final_protected_set_generated_at": self.final_protected_set_generated_at,
            "summary": self.summary,
            "records": [record.to_dict() for record in self.records],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _final_reason_lookup(final_protected_set: ProtectedSet | None) -> dict[str, tuple[str, ...]]:
    if final_protected_set is None:
        return {}
    return {record.artifact_id: tuple(record.protected_reason_codes) for record in final_protected_set.records}


def _record_from_plan(
    plan_record: LifecyclePlanRecord,
    *,
    final_reason_codes: tuple[str, ...] | None,
) -> QuarantineRecheckRecord:
    initially_blocked = bool(plan_record.protected or plan_record.protected_reason_codes)
    quarantine_candidate = plan_record.action == "quarantine_candidate" and not initially_blocked
    if initially_blocked:
        initial_check_status = "blocked"
        quarantine_state = "blocked_initial_protection"
        recheck_required = False
        recheck_status = "not_applicable"
        final_reasons = tuple(final_reason_codes or ())
        reason = "Initial lifecycle plan is protected; quarantine/delete cannot proceed."
    elif quarantine_candidate:
        initial_check_status = "clear"
        recheck_required = True
        if final_reason_codes is None:
            quarantine_state = "dry_run_candidate_pending_recheck"
            recheck_status = "not_performed"
            final_reasons = ()
            reason = "Initial plan is clear for quarantine candidate; final protected-set recheck evidence is still required."
        elif final_reason_codes:
            quarantine_state = "blocked_final_recheck"
            recheck_status = "blocked"
            final_reasons = final_reason_codes
            reason = "Final protected-set recheck found protection reasons; delete remains blocked."
        else:
            quarantine_state = "dry_run_recheck_clear"
            recheck_status = "clear"
            final_reasons = ()
            reason = "Final protected-set recheck is clear, but deletion still requires an approved executor and deletion receipt."
    else:
        initial_check_status = "clear"
        quarantine_candidate = False
        quarantine_state = "not_quarantine_candidate"
        recheck_required = False
        recheck_status = "not_applicable"
        final_reasons = tuple(final_reason_codes or ())
        reason = "Lifecycle plan action is not a quarantine/delete candidate."

    return QuarantineRecheckRecord(
        artifact_id=plan_record.artifact_id,
        artifact_kind=plan_record.artifact_kind,
        artifact_uri=plan_record.artifact_uri,
        physical_path=plan_record.physical_path,
        plan_action=plan_record.action,
        policy_id=plan_record.policy_id,
        rule_id=plan_record.rule_id,
        initial_protected=initially_blocked,
        initial_protected_reason_codes=tuple(plan_record.protected_reason_codes),
        initial_check_status=initial_check_status,
        quarantine_candidate=quarantine_candidate,
        quarantine_state=quarantine_state,
        recheck_required=recheck_required,
        recheck_status=recheck_status,
        final_protected_reason_codes=final_reasons,
        deletion_allowed=False,
        mutation_performed=False,
        reason=reason,
    )


def build_quarantine_recheck_evidence(
    lifecycle_plan: StorageLifecyclePlan,
    *,
    final_protected_set: ProtectedSet | None = None,
    generated_at: str | None = None,
) -> QuarantineRecheckEvidence:
    """Build report-only quarantine/recheck evidence from a lifecycle plan."""

    generated = generated_at or now_utc()
    lookup = _final_reason_lookup(final_protected_set)
    records = tuple(
        _record_from_plan(
            record,
            final_reason_codes=lookup.get(record.artifact_id) if final_protected_set is not None else None,
        )
        for record in lifecycle_plan.records
    )
    return QuarantineRecheckEvidence(
        contract_type="storage_quarantine_recheck_evidence",
        generated_at=generated,
        source_lifecycle_plan_generated_at=lifecycle_plan.generated_at,
        final_protected_set_generated_at=final_protected_set.generated_at if final_protected_set else None,
        records=records,
    )


def _plan_record_from_mapping(row: Mapping[str, Any]) -> LifecyclePlanRecord:
    values = dict(row)
    values["protected_reason_codes"] = tuple(values.get("protected_reason_codes", ()))
    return LifecyclePlanRecord(**values)


def load_storage_lifecycle_plan_json(path: Path) -> StorageLifecyclePlan:
    """Load a lifecycle-plan JSON file produced by the dry-run planner."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("lifecycle plan file must be a JSON object")
    rows = data.get("records", [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("lifecycle plan records must be an array")
    records: list[LifecyclePlanRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("lifecycle plan records must be JSON objects")
        records.append(_plan_record_from_mapping(row))
    return StorageLifecyclePlan(
        contract_type=str(data.get("contract_type", "storage_lifecycle_plan")),
        generated_at=str(data.get("generated_at", "")),
        dry_run=bool(data.get("dry_run", True)),
        records=tuple(records),
    )


def write_quarantine_recheck_evidence(
    evidence: QuarantineRecheckEvidence,
    *,
    output_path: Path,
    summary_path: Path | None = None,
) -> None:
    """Write quarantine/recheck evidence JSON and optional summary JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, evidence.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, evidence.summary_json())


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
    parser = argparse.ArgumentParser(description="Build dry-run quarantine/recheck evidence for lifecycle candidates.")
    parser.add_argument("--root", default=".", help="Repository/root directory for relative inputs and outputs.")
    parser.add_argument("--lifecycle-plan-json", help="Existing lifecycle-plan JSON path. Default builds a live dry-run plan.")
    parser.add_argument("--index-jsonl", help="Existing artifact-index JSONL path used when building a plan.")
    parser.add_argument("--protected-set-json", help="Initial protected-set JSON path used when building a plan.")
    parser.add_argument("--policy-file", help="JSON lifecycle policy file used when building a plan.")
    parser.add_argument("--include-root", action="append", dest="include_roots", help="Relative root/file for live artifact-index scan. Ignored when --lifecycle-plan-json or --index-jsonl is used.")
    parser.add_argument("--final-protected-set-json", help="Optional final protected-set JSON to evaluate recheck status.")
    parser.add_argument("--write", action="store_true", help="Write evidence JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_QUARANTINE_RECHECK_OUTPUT), help="Relative/absolute evidence JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_QUARANTINE_RECHECK_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full evidence JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    plan = _build_or_load_lifecycle_plan(args, root)
    final_protected_set = load_protected_set_json(_resolve_path(root, Path(args.final_protected_set_json))) if args.final_protected_set_json else None
    evidence = build_quarantine_recheck_evidence(plan, final_protected_set=final_protected_set)
    if args.write:
        write_quarantine_recheck_evidence(
            evidence,
            output_path=_resolve_path(root, Path(args.output_path)),
            summary_path=_resolve_path(root, Path(args.summary_path)),
        )
    if args.json:
        print(evidence.to_json(), end="")
    else:
        print(evidence.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
