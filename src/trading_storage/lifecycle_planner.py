"""Dry-run storage lifecycle planner for indexed durable artifacts.

The planner combines artifact-index metadata with protected-set evidence and
policy rules.  It only emits a plan; it never compresses, archives, quarantines,
deletes, detaches SQL, or mutates payloads.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading_storage.artifact_index import ArtifactIndex, ArtifactIndexRecord, DEFAULT_INDEX_ROOTS, build_artifact_index, now_utc
from trading_storage.io import write_text_atomic
from trading_storage.protected_set import (
    ProtectedSet,
    build_protected_set,
    load_artifact_index_jsonl,
)

LifecyclePlanAction = str

DEFAULT_LIFECYCLE_PLAN_OUTPUT = Path("storage/90_lifecycle/plans/storage_lifecycle_plan.json")
DEFAULT_LIFECYCLE_PLAN_SUMMARY_OUTPUT = Path("storage/90_lifecycle/plans/storage_lifecycle_plan_summary.json")


@dataclass(frozen=True)
class LifecyclePolicyRule:
    """One declarative lifecycle planning rule."""

    policy_id: str
    rule_id: str
    selector: dict[str, str]
    action: LifecyclePlanAction
    require_protected_set_clear: bool = True
    reason: str = ""


@dataclass(frozen=True)
class LifecyclePlanRecord:
    """One dry-run lifecycle recommendation for an artifact."""

    artifact_id: str
    artifact_kind: str
    dataset_id: str | None
    source_dataset_id: str | None
    transform_id: str | None
    artifact_uri: str
    physical_path: str
    action: LifecyclePlanAction
    policy_id: str | None
    rule_id: str | None
    protected: bool
    protected_reason_codes: tuple[str, ...]
    dry_run: bool
    reason: str
    artifact_size_bytes: int | None = None
    checksum_sha256: str | None = None
    content_codec: str | None = None
    content_format: str | None = None
    read_mode: str | None = None
    consumer_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StorageLifecyclePlan:
    """A dry-run lifecycle plan for durable indexed artifacts."""

    contract_type: str
    generated_at: str
    dry_run: bool
    records: tuple[LifecyclePlanRecord, ...]

    @property
    def summary(self) -> dict[str, Any]:
        action_counts: dict[str, int] = {}
        protected_block_count = 0
        for record in self.records:
            action_counts[record.action] = action_counts.get(record.action, 0) + 1
            if record.protected and record.action == "retain_protected":
                protected_block_count += 1
        return {
            "contract_type": "storage_lifecycle_plan_summary",
            "generated_at": self.generated_at,
            "dry_run": self.dry_run,
            "record_count": len(self.records),
            "action_counts": dict(sorted(action_counts.items())),
            "protected_block_count": protected_block_count,
            "mutation_performed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "dry_run": self.dry_run,
            "summary": self.summary,
            "records": [record.to_dict() for record in self.records],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


DEFAULT_POLICY_RULES: tuple[LifecyclePolicyRule, ...] = (
    LifecyclePolicyRule(
        policy_id="storage_lifecycle_default",
        rule_id="retain_receipts_and_evidence",
        selector={"artifact_kind_contains": "receipt"},
        action="retain_evidence",
        require_protected_set_clear=False,
        reason="Receipt/evidence artifacts are retained by default.",
    ),
    LifecyclePolicyRule(
        policy_id="storage_lifecycle_default",
        rule_id="retain_manual_review_required",
        selector={"retention_class": "manual_review_required"},
        action="retain_manual_review_required",
        require_protected_set_clear=False,
        reason="Metadata is insufficient for automated lifecycle action.",
    ),
    LifecyclePolicyRule(
        policy_id="storage_lifecycle_default",
        rule_id="compress_source_data",
        selector={"retention_class": "compress_and_retain", "content_codec": "none"},
        action="compress_candidate",
        require_protected_set_clear=True,
        reason="Uncompressed source-like artifacts may be compression candidates once unprotected.",
    ),
    LifecyclePolicyRule(
        policy_id="storage_lifecycle_default",
        rule_id="quarantine_ttl_delete_allowed",
        selector={"retention_class": "ttl_delete_allowed"},
        action="quarantine_candidate",
        require_protected_set_clear=True,
        reason="TTL-delete artifacts require quarantine-before-delete after protected-set clearance.",
    ),
    LifecyclePolicyRule(
        policy_id="storage_lifecycle_default",
        rule_id="quarantine_fold_complete_delete_allowed",
        selector={"retention_class": "fold_complete_delete_allowed"},
        action="quarantine_candidate",
        require_protected_set_clear=True,
        reason=(
            "Fold-scoped target/source artifacts may become deletion candidates only after the full "
            "M01-M06 fold closes and protected-set clearance remains clear."
        ),
    ),
)


def _record_value(record: ArtifactIndexRecord, key: str) -> str | None:
    value = getattr(record, key, None)
    return str(value) if value is not None else None


def _rule_matches(rule: LifecyclePolicyRule, record: ArtifactIndexRecord) -> bool:
    for key, expected in rule.selector.items():
        if key.endswith("_contains"):
            field_name = key.removesuffix("_contains")
            value = _record_value(record, field_name) or ""
            if expected not in value:
                return False
            continue
        if (_record_value(record, key) or "") != expected:
            return False
    return True


def _first_matching_rule(record: ArtifactIndexRecord, rules: Sequence[LifecyclePolicyRule]) -> LifecyclePolicyRule | None:
    for rule in rules:
        if _rule_matches(rule, record):
            return rule
    return None


def _artifact_identity_key(record: Any) -> tuple[str, str, str]:
    return (str(record.artifact_id), str(record.artifact_uri), str(record.physical_path))


def _protected_by_identity(protected_set: ProtectedSet) -> dict[tuple[str, str, str], Any]:
    return {_artifact_identity_key(record): record for record in protected_set.records}


def plan_storage_lifecycle(
    index: ArtifactIndex | Sequence[ArtifactIndexRecord],
    *,
    protected_set: ProtectedSet | None = None,
    rules: Sequence[LifecyclePolicyRule] = DEFAULT_POLICY_RULES,
    generated_at: str | None = None,
) -> StorageLifecyclePlan:
    """Create a dry-run lifecycle plan from artifact-index and protected-set evidence."""

    records = index.records if isinstance(index, ArtifactIndex) else tuple(index)
    protected = protected_set or build_protected_set(index)
    protected_lookup = _protected_by_identity(protected)
    generated = generated_at or now_utc()
    plan_records: list[LifecyclePlanRecord] = []

    for record in records:
        protected_record = protected_lookup.get(_artifact_identity_key(record))
        protected_reason_codes = tuple(protected_record.protected_reason_codes) if protected_record else tuple(record.protected_reason_codes)
        is_protected = bool(protected_reason_codes)
        rule = _first_matching_rule(record, rules)
        if is_protected:
            action = "retain_protected"
            policy_id = rule.policy_id if rule else None
            rule_id = rule.rule_id if rule else None
            reason = "Protected-set reasons block lifecycle mutation: " + ";".join(protected_reason_codes)
        elif rule is None:
            action = "retain_no_policy"
            policy_id = None
            rule_id = None
            reason = "No lifecycle policy rule matched; retain until reviewed."
        else:
            action = rule.action
            policy_id = rule.policy_id
            rule_id = rule.rule_id
            reason = rule.reason
            if rule.require_protected_set_clear and is_protected:
                action = "retain_protected"
                reason = "Protected-set clearance required and not available."
        plan_records.append(
            LifecyclePlanRecord(
                artifact_id=record.artifact_id,
                artifact_kind=record.artifact_kind,
                dataset_id=record.dataset_id,
                source_dataset_id=record.source_dataset_id,
                transform_id=record.transform_id,
                artifact_uri=record.artifact_uri,
                physical_path=record.physical_path,
                action=action,
                policy_id=policy_id,
                rule_id=rule_id,
                protected=is_protected,
                protected_reason_codes=protected_reason_codes,
                dry_run=True,
                reason=reason,
                artifact_size_bytes=record.artifact_size_bytes,
                checksum_sha256=record.checksum_sha256,
                content_codec=record.content_codec,
                content_format=record.content_format,
                read_mode=record.read_mode,
                consumer_refs=record.consumer_refs,
            )
        )

    return StorageLifecyclePlan(
        contract_type="storage_lifecycle_plan",
        generated_at=generated,
        dry_run=True,
        records=tuple(plan_records),
    )


def _rule_from_mapping(data: Mapping[str, Any]) -> LifecyclePolicyRule:
    selector = data.get("selector")
    if not isinstance(selector, Mapping):
        raise ValueError("policy rule selector must be an object")
    return LifecyclePolicyRule(
        policy_id=str(data["policy_id"]),
        rule_id=str(data["rule_id"]),
        selector={str(key): str(value) for key, value in selector.items()},
        action=str(data["action"]),
        require_protected_set_clear=bool(data.get("require_protected_set_clear", True)),
        reason=str(data.get("reason", "")),
    )


def load_policy_rules(path: Path) -> tuple[LifecyclePolicyRule, ...]:
    """Load lifecycle policy rules from JSON."""

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_rules = data.get("rules") if isinstance(data, Mapping) else data
    if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, (str, bytes, bytearray)):
        raise ValueError("policy file must be a JSON array or object with a rules array")
    return tuple(_rule_from_mapping(rule) for rule in raw_rules)


def load_protected_set_json(path: Path) -> ProtectedSet:
    """Load a protected-set JSON file produced by the protected-set builder."""

    from trading_storage.protected_set import ProtectedArtifact  # local import avoids exporting parser-only API there

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("protected-set file must be a JSON object")
    records = []
    for row in data.get("records", []):
        if not isinstance(row, Mapping):
            raise ValueError("protected-set records must be JSON objects")
        values = dict(row)
        values["protected_reason_codes"] = tuple(values.get("protected_reason_codes", ()))
        values["evidence_refs"] = tuple(values.get("evidence_refs", ()))
        records.append(ProtectedArtifact(**values))
    return ProtectedSet(
        contract_type=str(data.get("contract_type", "storage_protected_set")),
        generated_at=str(data.get("generated_at", "")),
        source_index_generated_at=data.get("source_index_generated_at"),
        records=tuple(records),
    )


def write_storage_lifecycle_plan(plan: StorageLifecyclePlan, *, output_path: Path, summary_path: Path | None = None) -> None:
    """Write dry-run lifecycle plan JSON and optional summary JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, plan.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, plan.summary_json())


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan storage lifecycle actions in dry-run mode.")
    parser.add_argument("--root", default=".", help="Repository/root directory for live index scans and relative outputs.")
    parser.add_argument("--index-jsonl", help="Existing artifact-index JSONL path. Default builds a live bounded index.")
    parser.add_argument("--protected-set-json", help="Existing protected-set JSON path. Default builds one from index evidence.")
    parser.add_argument("--policy-file", help="JSON lifecycle policy file. Default uses V0.1 conservative built-in rules.")
    parser.add_argument("--include-root", action="append", dest="include_roots", help="Relative root/file for live artifact-index scan. Ignored when --index-jsonl is used.")
    parser.add_argument("--write", action="store_true", help="Write plan JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_LIFECYCLE_PLAN_OUTPUT), help="Relative/absolute lifecycle plan JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_LIFECYCLE_PLAN_SUMMARY_OUTPUT), help="Relative/absolute lifecycle plan summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full lifecycle plan JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    if args.index_jsonl:
        index_or_records: ArtifactIndex | Sequence[ArtifactIndexRecord] = load_artifact_index_jsonl(_resolve_path(root, Path(args.index_jsonl)))
    else:
        index_or_records = build_artifact_index(root=root, include_roots=tuple(args.include_roots or DEFAULT_INDEX_ROOTS))
    protected_set = load_protected_set_json(_resolve_path(root, Path(args.protected_set_json))) if args.protected_set_json else None
    rules = load_policy_rules(_resolve_path(root, Path(args.policy_file))) if args.policy_file else DEFAULT_POLICY_RULES
    plan = plan_storage_lifecycle(index_or_records, protected_set=protected_set, rules=rules)
    if args.write:
        write_storage_lifecycle_plan(
            plan,
            output_path=_resolve_path(root, Path(args.output_path)),
            summary_path=_resolve_path(root, Path(args.summary_path)),
        )
    if args.json:
        print(plan.to_json(), end="")
    else:
        print(plan.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
