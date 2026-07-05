"""Storage-owned filesystem artifact index builder.

This module is the first concrete artifact-index implementation slice.  It
scans reviewed storage-owned filesystem roots, emits conservative metadata, and
writes optional JSONL index artifacts.  It never mutates indexed payloads and it
intentionally classifies ambiguous files as protected by unknown metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from trading_storage.io import write_text_atomic

DEFAULT_INDEX_ROOTS = (
    "storage/01_source_data",
    "storage/02_control_plane",
    "storage/03_model_artifacts",
    "storage/04_execution_artifacts",
    "storage/05_replay_datasets",
    "storage/06_dashboard_cache/read_models",
)
DEFAULT_INDEX_OUTPUT = Path("storage/90_lifecycle/artifact_index/artifact_index.jsonl")
DEFAULT_SUMMARY_OUTPUT = Path("storage/90_lifecycle/artifact_index/artifact_index_summary.json")

_FORMAT_BY_SUFFIX = {
    ".json": "json",
    ".jsonl": "jsonl",
    ".csv": "csv",
    ".parquet": "parquet",
    ".txt": "text",
    ".log": "text",
    ".md": "markdown",
    ".sql": "sql",
    ".dump": "pg_dump",
}
_COMPRESSED_SUFFIXES = {
    ".zst": "zstd",
    ".gz": "gzip",
    ".zip": "zip",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class ArtifactIndexRecord:
    """One conservative artifact-index row."""

    artifact_id: str
    artifact_kind: str
    dataset_id: str | None
    source_dataset_id: str | None
    transform_id: str | None
    producer_repo: str
    producer_component: str
    producer_run_id: str | None
    artifact_uri: str
    physical_path: str
    storage_backend: str
    created_at: str
    available_time: str
    artifact_size_bytes: int
    checksum_sha256: str
    content_codec: str
    content_format: str
    read_mode: str
    schema_ref: str | None
    manifest_ref: str | None
    schema_version: str | None = None
    consumer_refs: tuple[str, ...] = field(default_factory=tuple)
    lineage_refs: tuple[str, ...] = field(default_factory=tuple)
    dependency_refs: tuple[str, ...] = field(default_factory=tuple)
    reproducibility_class: str = "unknown"
    retention_class: str = "manual_review_required"
    lifecycle_state: str = "indexed"
    protected_reason_codes: tuple[str, ...] = ("unknown_metadata",)
    last_lifecycle_scan_at: str | None = None
    last_lifecycle_action_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactIndex:
    """A deterministic filesystem artifact-index build result."""

    root: str
    generated_at: str
    scanned_roots: tuple[str, ...]
    records: tuple[ArtifactIndexRecord, ...]

    @property
    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        by_retention: dict[str, int] = {}
        total_bytes = 0
        for record in self.records:
            by_kind[record.artifact_kind] = by_kind.get(record.artifact_kind, 0) + 1
            by_retention[record.retention_class] = by_retention.get(record.retention_class, 0) + 1
            total_bytes += record.artifact_size_bytes
        return {
            "contract_type": "storage_artifact_index_summary",
            "generated_at": self.generated_at,
            "root": self.root,
            "scanned_roots": list(self.scanned_roots),
            "record_count": len(self.records),
            "total_artifact_size_bytes": total_bytes,
            "artifact_kind_counts": dict(sorted(by_kind.items())),
            "retention_class_counts": dict(sorted(by_retention.items())),
        }

    def to_jsonl(self) -> str:
        return "".join(json.dumps(record.to_dict(), sort_keys=True) + "\n" for record in self.records)

    def summary_json(self) -> str:
        return json.dumps(self.summary, indent=2, sort_keys=True) + "\n"


def _iter_indexable_files(root: Path, include_roots: Sequence[str]) -> Iterable[Path]:
    for relative in include_roots:
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"unsafe include root: {relative!r}")
        base = root / relative
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.is_symlink():
                yield path


def _load_json_object(path: Path) -> Mapping[str, Any] | None:
    if path.suffix.lower() != ".json":
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, Mapping) else None


def _content_format(path: Path) -> str:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes and suffixes[-1] in _COMPRESSED_SUFFIXES and len(suffixes) >= 2:
        return _FORMAT_BY_SUFFIX.get(suffixes[-2], suffixes[-2].lstrip(".") or "binary")
    if suffixes:
        return _FORMAT_BY_SUFFIX.get(suffixes[-1], suffixes[-1].lstrip(".") or "binary")
    return "binary"


def _content_codec(path: Path) -> str:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes[-2:] == [".tar", ".zst"]:
        return "tar_zstd"
    if suffixes and suffixes[-1] in _COMPRESSED_SUFFIXES:
        return _COMPRESSED_SUFFIXES[suffixes[-1]]
    return "none"


def _read_mode(content_codec: str) -> str:
    if content_codec == "none":
        return "direct_readable"
    return "restore_required"


def _explicit_artifact_id(data: Mapping[str, Any] | None) -> str | None:
    if data and data.get("artifact_id"):
        return str(data["artifact_id"])
    return None


def _artifact_id(relative_path: Path, data: Mapping[str, Any] | None, checksum: str) -> str:
    explicit = _explicit_artifact_id(data)
    if explicit:
        return explicit
    normalized_path = str(relative_path).replace("\\", "/")
    return "art_idx_" + hashlib.sha256((normalized_path + "\0" + checksum).encode("utf-8")).hexdigest()[:24]


def _artifact_kind(relative_path: Path, data: Mapping[str, Any] | None) -> str:
    if data:
        contract_type = data.get("contract_type")
        if contract_type == "component_completion_receipt_payload":
            return "component_completion_receipt_payload"
        if contract_type:
            return str(contract_type)
    if len(relative_path.parts) >= 2 and relative_path.parts[0] == "storage" and relative_path.parts[1] == "06_dashboard_cache":
        return "dashboard_read_model_payload"
    if len(relative_path.parts) >= 4 and relative_path.parts[:3] == ("storage", "02_control_plane", "artifacts"):
        return relative_path.parts[3]
    return "filesystem_artifact"


def _producer_repo(relative_path: Path, data: Mapping[str, Any] | None) -> str:
    if data:
        for key in ("producer_repo", "source_repo"):
            value = data.get(key)
            if value:
                return str(value)
    return "trading-storage"


def _producer_component(relative_path: Path, data: Mapping[str, Any] | None) -> str:
    if data:
        for key in ("producer_workflow", "producer_component", "workflow_id", "contract_type"):
            value = data.get(key)
            if value:
                return str(value)
    if len(relative_path.parts) >= 4 and relative_path.parts[:3] == ("storage", "06_dashboard_cache", "read_models"):
        return relative_path.stem
    if len(relative_path.parts) >= 4 and relative_path.parts[:3] == ("storage", "02_control_plane", "artifacts"):
        return relative_path.parts[3]
    return "filesystem_scan"


def _producer_run_id(data: Mapping[str, Any] | None) -> str | None:
    if not data:
        return None
    for key in ("run_id", "manifest_id", "producer_run_id"):
        value = data.get(key)
        if value:
            return str(value)
    receipt = data.get("receipt")
    if isinstance(receipt, Mapping) and receipt.get("run_id"):
        return str(receipt["run_id"])
    return None


def _schema_ref(data: Mapping[str, Any] | None) -> str | None:
    if not data:
        return None
    for key in ("schema_ref", "schema_uri"):
        value = data.get(key)
        if value is not None:
            return str(value)
    contract_type = data.get("contract_type")
    if contract_type:
        return f"storage/06_dashboard_cache/schemas/{contract_type}.schema.json"
    return None


def _schema_version(data: Mapping[str, Any] | None) -> str | None:
    if not data or data.get("schema_version") is None:
        return None
    return str(data["schema_version"])


def _manifest_ref(data: Mapping[str, Any] | None) -> str | None:
    if not data:
        return None
    for key in ("manifest_ref", "manifest_id"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _dataset_id(data: Mapping[str, Any] | None) -> str | None:
    return _metadata_string(data, "dataset_id", "derived_dataset_id")


def _source_dataset_id(data: Mapping[str, Any] | None) -> str | None:
    return _metadata_string(data, "source_dataset_id", "parent_dataset_id")


def _transform_id(data: Mapping[str, Any] | None) -> str | None:
    return _metadata_string(data, "transform_id", "granularity", "timeframe")


def _sequence_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if item is not None)
    return ()


def _consumer_refs(data: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not data:
        return ()
    refs: list[str] = []
    for key in ("consumer_refs", "consumer_ref", "consumers"):
        refs.extend(_sequence_strings(data.get(key)))
    return tuple(dict.fromkeys(refs))


def _lineage_refs(data: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not data:
        return ()
    refs: list[str] = []
    for key in ("lineage_refs", "source_refs", "input_refs"):
        refs.extend(_sequence_strings(data.get(key)))
    return tuple(dict.fromkeys(refs))


def _dependency_refs(data: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not data:
        return ()
    refs: list[str] = []
    for key in ("dependency_refs", "artifact_refs", "output_refs"):
        refs.extend(_sequence_strings(data.get(key)))
    return tuple(dict.fromkeys(refs))


def _metadata_string(data: Mapping[str, Any] | None, *keys: str) -> str | None:
    if not data:
        return None
    for key in keys:
        value = data.get(key)
        if value is not None and str(value):
            return str(value)
    return None


def _classification_text(
    relative_path: Path,
    *,
    data: Mapping[str, Any] | None,
    artifact_kind: str,
    producer_component: str,
) -> str:
    fields: list[str] = [str(relative_path).replace("\\", "/"), artifact_kind, producer_component]
    if data:
        for key in ("contract_type", "model_layer", "layer", "workflow_id", "source_system", "schema_ref"):
            value = data.get(key)
            if value is not None:
                fields.append(str(value))
        fields.extend(_sequence_strings(data.get("lineage_refs")))
        fields.extend(_sequence_strings(data.get("diagnostic_refs")))
    return "\n".join(fields).lower()


def _is_dashboard_snapshot(relative_path: Path) -> bool:
    return (
        len(relative_path.parts) >= 5
        and relative_path.parts[:3] == ("storage", "06_dashboard_cache", "read_models")
        and relative_path.parts[4] == "snapshots"
    )


def _is_dashboard_latest(relative_path: Path) -> bool:
    return len(relative_path.parts) == 4 and relative_path.parts[:3] == ("storage", "06_dashboard_cache", "read_models") and relative_path.suffix == ".json"


def _is_dashboard_active_input(relative_path: Path) -> bool:
    normalized = str(relative_path).replace("\\", "/")
    if normalized in {
        "storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl",
        "storage/02_control_plane/runtime/historical_scheduler_state.json",
        "storage/04_execution_artifacts/runtime/realtime_trading_runtime/runtime_status.json",
    }:
        return True
    if (
        len(relative_path.parts) == 4
        and relative_path.parts[:3] == ("storage", "02_control_plane", "runtime")
        and relative_path.name.startswith("model_training_workflow_state")
        and relative_path.suffix == ".json"
    ):
        return True
    return (
        len(relative_path.parts) >= 5
        and relative_path.parts[:3] == ("storage", "02_control_plane", "runtime")
        and relative_path.parts[3] in {"stage_coverage", "stage_run_dashboard"}
        and relative_path.suffix == ".json"
    )


def _has_m01_m02_marker(text: str) -> bool:
    return any(token in text for token in ("model_01", "model_02", "feature_01", "feature_02", "m01", "m02"))


def _has_disposable_runtime_marker(text: str) -> bool:
    return any(
        token in text
        for token in (
            "cache",
            "failed_run",
            "intermediate",
            "log",
            "logs",
            "runtime",
            "scratch",
            "staging",
            "stderr",
            "stdout",
            "tmp",
        )
    )


def _is_durable_boundary_evidence(relative_path: Path, text: str) -> bool:
    filename = relative_path.name.lower()
    if relative_path.parts[:3] == ("storage", "90_lifecycle", "artifact_index"):
        return True
    return any(
        token in text or token in filename
        for token in (
            "archive_manifest",
            "archive_receipt",
            "compression_manifest",
            "compression_receipt",
            "delete_receipt",
            "deletion_receipt",
            "executed_lifecycle_plan",
            "lifecycle_decision",
            "quarantine_recheck",
            "restore_receipt",
            "storage_lifecycle_plan",
            "tombstone",
        )
    )


def _is_runtime_byproduct_file(relative_path: Path, text: str) -> bool:
    if _is_durable_boundary_evidence(relative_path, text):
        return False
    filename = relative_path.name.lower()
    if filename.endswith(".log"):
        return True
    if any(token in filename for token in ("progress", "runtime_trace", "checkpoint")):
        return True
    if filename not in {"request_manifest.json", "completion_receipt.json"}:
        return False
    return any(
        token in text
        for token in (
            "/runs/",
            "/runtime/",
            "/recent_refresh_runs/",
            "/feed/",
            "te_recent_calendar_refresh",
        )
    )


def _is_replay_path(relative_path: Path) -> bool:
    return len(relative_path.parts) >= 2 and relative_path.parts[:2] == ("storage", "05_replay_datasets")


def _has_replay_result_summary_marker(text: str) -> bool:
    return "replay" in text and any(
        token in text
        for token in (
            "baseline_comparison",
            "model_pipeline_replay_result_summary",
            "pipeline_replay_result_summary",
            "promotion_replay_result",
            "result_summary",
            "scorecard",
        )
    )


def _has_reusable_replay_input_marker(text: str) -> bool:
    return "replay" in text and any(
        token in text
        for token in (
            "market_regime",
            "sector_context",
        )
    )


def _has_event_interpretation_marker(text: str) -> bool:
    return any(
        token in text
        for token in (
            "event_interpretation",
            "event_interpretations",
            "interpreted_event",
            "semantic_event",
            "standardized_event",
        )
    )


def _has_refetchable_event_original_marker(text: str) -> bool:
    return any(
        token in text
        for token in (
            "downloaded_event",
            "downloaded_news",
            "event_news",
            "event_original",
            "event_source_news",
            "raw_event",
            "raw_news",
            "source_news",
        )
    )


def _has_trading_economics_marker(text: str) -> bool:
    return any(token in text for token in ("trading_economics", "te_recent_calendar_refresh"))


def _has_model_specific_replay_download_marker(text: str) -> bool:
    return "replay" in text and any(
        token in text
        for token in (
            "model_specific_download",
            "model_pipeline_download",
            "option_chain",
            "option_snapshot",
            "options_snapshot",
            "point_in_time_option",
            "theta_snapshot",
        )
    )


def _retention_class(
    relative_path: Path,
    *,
    data: Mapping[str, Any] | None,
    artifact_kind: str,
    producer_component: str,
) -> str:
    explicit = _metadata_string(data, "storage_retention_class", "retention_class")
    if explicit:
        return explicit
    text = _classification_text(relative_path, data=data, artifact_kind=artifact_kind, producer_component=producer_component)
    if _is_dashboard_latest(relative_path):
        return "dashboard_latest_retained"
    if _is_dashboard_snapshot(relative_path):
        return "ttl_delete_allowed"
    if _is_dashboard_active_input(relative_path):
        return "dashboard_active_input_retained"
    if _is_durable_boundary_evidence(relative_path, text):
        return "keep_forever"
    if _is_runtime_byproduct_file(relative_path, text):
        return "ttl_delete_allowed"
    if _has_trading_economics_marker(text):
        return "keep_forever"
    if _is_replay_path(relative_path) and _has_replay_result_summary_marker(text):
        return "keep_forever"
    if _has_event_interpretation_marker(text):
        return "keep_forever"
    if _has_refetchable_event_original_marker(text):
        return "ttl_delete_allowed"
    if _is_replay_path(relative_path) and _has_model_specific_replay_download_marker(text):
        return "ttl_delete_allowed"
    if _is_replay_path(relative_path) and _has_reusable_replay_input_marker(text):
        return "compress_and_retain"
    if _has_m01_m02_marker(text) and _has_disposable_runtime_marker(text):
        return "ttl_delete_allowed"
    if _has_m01_m02_marker(text):
        return "compress_and_retain"
    if any(
        token in text
        for token in (
            "model_03",
            "model_04",
            "model_05",
            "m05_option_expression_feature_generation",
            "m05_option_expression_data_acquisition_contract_path",
            "m03_event_state_feature_generation",
            "m03_event_state_data_acquisition",
            "event_effect_model",
        )
    ) and any(token in text for token in ("metadata", "summary", "diagnostic", "scratch", "intermediate", "runtime", "staging")):
        return "ttl_delete_allowed"
    return "manual_review_required"


def _reproducibility_class(data: Mapping[str, Any] | None) -> str:
    return _metadata_string(data, "storage_reproducibility_class", "reproducibility_class") or "unknown"


def _protected_reason_codes(retention_class: str, *, classification_text: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if retention_class == "manual_review_required":
        reasons.append("unknown_metadata")
    if retention_class == "dashboard_latest_retained":
        reasons.append("dashboard_latest_snapshot")
    if retention_class == "dashboard_active_input_retained":
        reasons.append("dashboard_active_input")
    if retention_class == "keep_forever" and _has_replay_result_summary_marker(classification_text):
        reasons.append("replay_result_summary")
    elif retention_class == "keep_forever" and _has_event_interpretation_marker(classification_text):
        reasons.append("event_interpretation_evidence")
    elif retention_class == "keep_forever":
        reasons.append("keep_forever_retention")
    return tuple(dict.fromkeys(reasons))


def build_artifact_index(
    root: Path = Path("."),
    *,
    include_roots: Sequence[str] = DEFAULT_INDEX_ROOTS,
    generated_at: str | None = None,
) -> ArtifactIndex:
    """Build a conservative filesystem artifact index without mutating artifacts."""

    root = root.resolve()
    scan_time = generated_at or now_utc()
    records: list[ArtifactIndexRecord] = []
    explicit_artifact_paths: dict[str, Path] = {}
    for path in _iter_indexable_files(root, include_roots):
        relative = path.relative_to(root)
        data = _load_json_object(path)
        stat = path.stat()
        checksum = sha256_file(path)
        content_codec = _content_codec(path)
        explicit_id = _explicit_artifact_id(data)
        artifact_id = _artifact_id(relative, data, checksum)
        if explicit_id:
            previous = explicit_artifact_paths.get(explicit_id)
            if previous is not None:
                raise ValueError(
                    "duplicate explicit artifact_id "
                    f"{explicit_id!r} for {previous.as_posix()} and {relative.as_posix()}"
                )
            explicit_artifact_paths[explicit_id] = relative
        artifact_kind = _artifact_kind(relative, data)
        producer_component = _producer_component(relative, data)
        retention_class = _retention_class(relative, data=data, artifact_kind=artifact_kind, producer_component=producer_component)
        created_at = _iso_from_timestamp(stat.st_mtime)
        consumer_refs = _consumer_refs(data)
        protected_reason_codes = list(
            _protected_reason_codes(
                retention_class,
                classification_text=_classification_text(relative, data=data, artifact_kind=artifact_kind, producer_component=producer_component),
            )
        )
        if consumer_refs and "active_consumer_ref" not in protected_reason_codes:
            protected_reason_codes.append("active_consumer_ref")
        records.append(
            ArtifactIndexRecord(
                artifact_id=artifact_id,
                artifact_kind=artifact_kind,
                dataset_id=_dataset_id(data),
                source_dataset_id=_source_dataset_id(data),
                transform_id=_transform_id(data),
                producer_repo=_producer_repo(relative, data),
                producer_component=producer_component,
                producer_run_id=_producer_run_id(data),
                artifact_uri="storage://trading-storage/" + str(relative).replace("\\", "/"),
                physical_path=str(relative).replace("\\", "/"),
                storage_backend="filesystem",
                created_at=created_at,
                available_time=created_at,
                artifact_size_bytes=stat.st_size,
                checksum_sha256=checksum,
                content_codec=content_codec,
                content_format=_content_format(path),
                read_mode=_read_mode(content_codec),
                schema_ref=_schema_ref(data),
                manifest_ref=_manifest_ref(data),
                schema_version=_schema_version(data),
                consumer_refs=consumer_refs,
                lineage_refs=_lineage_refs(data),
                dependency_refs=_dependency_refs(data),
                reproducibility_class=_reproducibility_class(data),
                retention_class=retention_class,
                protected_reason_codes=tuple(protected_reason_codes),
                last_lifecycle_scan_at=scan_time,
            )
        )
    return ArtifactIndex(
        root=str(root),
        generated_at=scan_time,
        scanned_roots=tuple(include_roots),
        records=tuple(records),
    )


def write_artifact_index(index: ArtifactIndex, *, index_path: Path, summary_path: Path | None = None) -> None:
    """Write index JSONL and optional summary JSON."""

    root = Path(index.root)
    output = index_path if index_path.is_absolute() else root / index_path
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output, index.to_jsonl())
    if summary_path is not None:
        summary = summary_path if summary_path.is_absolute() else root / summary_path
        summary.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(summary, index.summary_json())


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the storage-owned filesystem artifact index.")
    parser.add_argument("--root", default=".", help="Repository/root directory to scan.")
    parser.add_argument(
        "--include-root",
        action="append",
        dest="include_roots",
        help="Relative root/file to include. May be repeated. Defaults to storage artifacts only; add specific current read-model files or bounded roots explicitly.",
    )
    parser.add_argument("--write", action="store_true", help="Write JSONL index and summary files. Default prints summary only.")
    parser.add_argument("--index-path", default=str(DEFAULT_INDEX_OUTPUT), help="Relative/absolute JSONL index output path.")
    parser.add_argument("--summary-path", default=str(DEFAULT_SUMMARY_OUTPUT), help="Relative/absolute summary JSON output path.")
    parser.add_argument("--jsonl", action="store_true", help="Print JSONL records instead of summary JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    index = build_artifact_index(root=Path(args.root), include_roots=tuple(args.include_roots or DEFAULT_INDEX_ROOTS))
    if args.write:
        write_artifact_index(index, index_path=Path(args.index_path), summary_path=Path(args.summary_path))
    if args.jsonl:
        print(index.to_jsonl(), end="")
    else:
        print(index.summary_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
