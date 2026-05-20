"""Storage protected-set builder for lifecycle safety gates.

The protected set is deliberately conservative: anything with ambiguous or
insufficient metadata remains protected until a later reviewed classifier proves
otherwise.  This module only builds evidence; it does not archive, compress,
delete, detach SQL, or mutate indexed payloads.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading_storage.artifact_index import ArtifactIndex, ArtifactIndexRecord, DEFAULT_INDEX_ROOTS, build_artifact_index, now_utc
from trading_storage.io import write_text_atomic

DEFAULT_PROTECTED_SET_OUTPUT = Path("storage/90_lifecycle/protected_set/protected_set.json")
DEFAULT_PROTECTED_SET_SUMMARY_OUTPUT = Path("storage/90_lifecycle/protected_set/protected_set_summary.json")

PROTECTED_REASON_CODES = frozenset(
    {
        "current_promoted_model_lineage",
        "old_promoted_model_body",
        "active_review_lineage",
        "active_run_input_or_output",
        "ready_signal_consumable",
        "dataset_snapshot_or_split",
        "active_target_chain_dependency",
        "source_data_shared_dependency",
        "sql_online_dependency",
        "manual_pin",
        "unknown_metadata",
        "dashboard_latest_snapshot",
        "benchmark_result_summary",
        "keep_forever_retention",
    }
)

_REFERENCE_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_uri",
        "physical_path",
        "producer_run_id",
        "schema_ref",
        "manifest_ref",
        "lineage_refs",
        "dependency_refs",
    }
)


@dataclass(frozen=True)
class ProtectedArtifact:
    """One protected-set decision for an indexed artifact."""

    artifact_id: str
    artifact_kind: str
    artifact_uri: str
    physical_path: str
    protected_reason_codes: tuple[str, ...]
    candidate_requested: bool
    protected: bool
    mutation_allowed: bool
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProtectedSet:
    """A deterministic protected-set build result."""

    contract_type: str
    generated_at: str
    source_index_generated_at: str | None
    records: tuple[ProtectedArtifact, ...]

    @property
    def summary(self) -> dict[str, Any]:
        reason_counts: dict[str, int] = {}
        candidate_count = 0
        protected_count = 0
        mutation_allowed_count = 0
        for record in self.records:
            if record.candidate_requested:
                candidate_count += 1
            if record.protected:
                protected_count += 1
            if record.mutation_allowed:
                mutation_allowed_count += 1
            for reason in record.protected_reason_codes:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        candidate_protected = sum(1 for record in self.records if record.candidate_requested and record.protected)
        candidate_clear = sum(1 for record in self.records if record.candidate_requested and record.mutation_allowed)
        return {
            "contract_type": "storage_protected_set_summary",
            "generated_at": self.generated_at,
            "source_index_generated_at": self.source_index_generated_at,
            "record_count": len(self.records),
            "protected_count": protected_count,
            "mutation_allowed_count": mutation_allowed_count,
            "candidate_count": candidate_count,
            "candidate_protected_count": candidate_protected,
            "candidate_clear_count": candidate_clear,
            "candidate_mutation_allowed": candidate_count > 0 and candidate_protected == 0,
            "reason_counts": dict(sorted(reason_counts.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at": self.generated_at,
            "source_index_generated_at": self.source_index_generated_at,
            "summary": self.summary,
            "records": [record.to_dict() for record in self.records],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _normalize_reasons(reason_codes: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(reason) for reason in reason_codes if reason))
    unknown = [reason for reason in normalized if reason not in PROTECTED_REASON_CODES]
    if unknown:
        raise ValueError(f"unknown protected reason code(s): {', '.join(unknown)}")
    return normalized


def _record_reference_tokens(record: ArtifactIndexRecord) -> tuple[str, ...]:
    tokens: list[str] = []
    for key in _REFERENCE_KEYS:
        value = getattr(record, key)
        tokens.extend(_tuple_strings(value))
    return tuple(token for token in dict.fromkeys(tokens) if token)


def _reference_map(reference_sets: Mapping[str, Sequence[str]] | None) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    if not reference_sets:
        return result
    _normalize_reasons(tuple(reference_sets.keys()))
    for reason, values in reference_sets.items():
        result[str(reason)] = set(_tuple_strings(values))
    return result


def _candidate_tokens(candidate_refs: Sequence[str] | None) -> set[str]:
    return set(_tuple_strings(tuple(candidate_refs or ())))


def build_protected_set(
    index: ArtifactIndex | Sequence[ArtifactIndexRecord],
    *,
    reference_sets: Mapping[str, Sequence[str]] | None = None,
    manual_pins: Sequence[str] | None = None,
    candidate_refs: Sequence[str] | None = None,
    generated_at: str | None = None,
) -> ProtectedSet:
    """Build a conservative protected set from artifact-index records."""

    if isinstance(index, ArtifactIndex):
        records = index.records
        source_index_generated_at: str | None = index.generated_at
    else:
        records = tuple(index)
        source_index_generated_at = None
    generated = generated_at or now_utc()
    refs_by_reason = _reference_map(reference_sets)
    manual_pin_tokens = set(_tuple_strings(tuple(manual_pins or ())))
    candidates = _candidate_tokens(candidate_refs)
    protected_records: list[ProtectedArtifact] = []

    for record in records:
        tokens = set(_record_reference_tokens(record))
        reasons: list[str] = list(_normalize_reasons(record.protected_reason_codes))
        evidence_refs: list[str] = []

        for reason, refs in refs_by_reason.items():
            matches = tokens.intersection(refs)
            if matches and reason not in reasons:
                reasons.append(reason)
                evidence_refs.extend(sorted(matches))
        manual_matches = tokens.intersection(manual_pin_tokens)
        if manual_matches and "manual_pin" not in reasons:
            reasons.append("manual_pin")
            evidence_refs.extend(sorted(manual_matches))

        candidate_requested = bool(candidates and tokens.intersection(candidates))
        protected = bool(reasons)
        protected_records.append(
            ProtectedArtifact(
                artifact_id=record.artifact_id,
                artifact_kind=record.artifact_kind,
                artifact_uri=record.artifact_uri,
                physical_path=record.physical_path,
                protected_reason_codes=tuple(dict.fromkeys(reasons)),
                candidate_requested=candidate_requested,
                protected=protected,
                mutation_allowed=not protected,
                evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            )
        )

    return ProtectedSet(
        contract_type="storage_protected_set",
        generated_at=generated,
        source_index_generated_at=source_index_generated_at,
        records=tuple(protected_records),
    )


def _artifact_index_record_from_dict(row: Mapping[str, Any]) -> ArtifactIndexRecord:
    names = {field.name for field in fields(ArtifactIndexRecord)}
    kwargs: dict[str, Any] = {key: row[key] for key in names if key in row}
    for key in ("lineage_refs", "dependency_refs", "protected_reason_codes"):
        if key in kwargs:
            kwargs[key] = tuple(kwargs[key])
    return ArtifactIndexRecord(**kwargs)


def load_artifact_index_jsonl(path: Path) -> tuple[ArtifactIndexRecord, ...]:
    """Load artifact-index records from JSONL produced by the artifact-index builder."""

    records: list[ArtifactIndexRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(data, Mapping):
                raise ValueError(f"artifact index row must be an object at {path}:{line_number}")
            records.append(_artifact_index_record_from_dict(data))
    return tuple(records)


def load_reference_sets(path: Path) -> dict[str, tuple[str, ...]]:
    """Load protected reason-code reference sets from JSON."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("reference file must be a JSON object keyed by protected reason code")
    result: dict[str, tuple[str, ...]] = {}
    for reason, refs in data.items():
        result[str(reason)] = _tuple_strings(refs)
    _reference_map(result)
    return result


def write_protected_set(protected_set: ProtectedSet, *, output_path: Path, summary_path: Path | None = None) -> None:
    """Write protected-set JSON and optional summary JSON."""

    output = output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output, protected_set.to_json())
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary_path, protected_set.summary_json())


def _resolve_output_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the storage protected set for lifecycle safety gates.")
    parser.add_argument("--root", default=".", help="Repository/root directory used for live artifact-index scans and relative outputs.")
    parser.add_argument("--index-jsonl", help="Existing artifact-index JSONL path. Default builds a live bounded index.")
    parser.add_argument(
        "--include-root",
        action="append",
        dest="include_roots",
        help="Relative root/file for live artifact-index scan. May be repeated. Ignored when --index-jsonl is used.",
    )
    parser.add_argument("--reference-file", help="JSON object keyed by protected reason code with artifact id/URI/path refs.")
    parser.add_argument("--manual-pin", action="append", dest="manual_pins", help="Artifact id/URI/path/ref to protect as manual_pin. May be repeated.")
    parser.add_argument("--candidate", action="append", dest="candidates", help="Artifact id/URI/path/ref to evaluate as a mutation candidate. May be repeated.")
    parser.add_argument("--write", action="store_true", help="Write protected-set JSON and summary files. Default prints summary only.")
    parser.add_argument("--output-path", default=str(DEFAULT_PROTECTED_SET_OUTPUT), help="Relative/absolute protected-set JSON output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_PROTECTED_SET_SUMMARY_OUTPUT), help="Relative/absolute protected-set summary JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print full protected-set JSON instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    if args.index_jsonl:
        index_or_records: ArtifactIndex | Sequence[ArtifactIndexRecord] = load_artifact_index_jsonl(_resolve_output_path(root, Path(args.index_jsonl)))
    else:
        index_or_records = build_artifact_index(root=root, include_roots=tuple(args.include_roots or DEFAULT_INDEX_ROOTS))
    reference_sets = load_reference_sets(_resolve_output_path(root, Path(args.reference_file))) if args.reference_file else None
    protected_set = build_protected_set(
        index_or_records,
        reference_sets=reference_sets,
        manual_pins=tuple(args.manual_pins or ()),
        candidate_refs=tuple(args.candidates or ()),
    )
    if args.write:
        write_protected_set(
            protected_set,
            output_path=_resolve_output_path(root, Path(args.output_path)),
            summary_path=_resolve_output_path(root, Path(args.summary_path)),
        )
    if args.json:
        print(protected_set.to_json(), end="")
    else:
        print(protected_set.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
