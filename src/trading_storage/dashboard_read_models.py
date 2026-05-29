"""Dashboard read-model storage helpers.

This module implements the first storage-side writer/validation slice for
owner-facing dashboard summaries.  It materializes validated JSON documents
under the accepted ``storage/06_dashboard_cache`` layout without creating dashboard UI,
refresh jobs, provider calls, model activation, broker execution, or account
mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from trading_storage.artifact_store import canonical_json_bytes, now_utc
from trading_storage.io import append_text_locked

DEFAULT_STORAGE_ROOT = Path("storage")
DASHBOARD_ROOT = Path("06_dashboard_cache")
INDEX_PATH = DASHBOARD_ROOT / "index" / "dashboard_read_model_index.jsonl"
CLOCK_SKEW = timedelta(minutes=5)

REFRESHABLE_CONTRACT_TYPES = frozenset(
    {
        "current_system_status_summary",
        "historical_task_progress_summary",
        "realtime_signal_summary",
        "temporal_explorer_summary",
        "execution_realtime_trading_runtime_status",
    }
)
PARKED_CONTRACT_TYPES = frozenset(
    {
        "alert_exception_summary",
        "realtime_task_progress_summary",
        "model_layer_readiness_summary",
        "model_promotion_posture_summary",
        "registry_dictionary_profile",
        "runtime_decision_quality_summary",
        "trading_performance_summary",
        "storage_lifecycle_status_summary",
    }
)
REGISTERED_CONTRACT_TYPES = REFRESHABLE_CONTRACT_TYPES | PARKED_CONTRACT_TYPES

REQUIRED_ENVELOPE_FIELDS = (
    "contract_type",
    "schema_version",
    "generated_at_utc",
    "source_system",
    "status",
    "summary",
    "chart_payload",
    "profile_refs",
    "issue_refs",
    "diagnostic_refs",
    "lineage_refs",
    "freshness",
    "schema_ref",
)
SEVERITY_VALUES = frozenset({"critical", "high", "medium", "low", "info"})
SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|passphrase|credential|private[_-]?key)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})"
)
SAFE_CONTRACT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class DashboardReadModelError(ValueError):
    """Raised when a dashboard read model is invalid or unsafe."""


@dataclass(frozen=True)
class MaterializedDashboardReadModel:
    """Metadata for one materialized dashboard read-model snapshot."""

    contract_type: str
    latest_path: Path
    snapshot_path: Path
    schema_path: Path
    index_path: Path
    content_hash: str
    snapshot_state_hash: str
    byte_count: int
    generated_at_utc: str
    storage_uri: str
    snapshot_written: bool
    index_written: bool
    write_mode: str
    index_row: dict[str, Any]


def _parse_utc_timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DashboardReadModelError(f"{field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise DashboardReadModelError(f"{field} is not a valid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise DashboardReadModelError(f"{field} must include UTC timezone")
    return parsed.astimezone(timezone.utc)


def _compact_timestamp(value: str) -> str:
    parsed = _parse_utc_timestamp(value, field="generated_at_utc")
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _safe_contract_type(contract_type: str) -> str:
    if not isinstance(contract_type, str) or not SAFE_CONTRACT_RE.fullmatch(contract_type):
        raise DashboardReadModelError(f"unsafe or unregistered-shaped contract_type: {contract_type!r}")
    if contract_type not in REGISTERED_CONTRACT_TYPES:
        raise DashboardReadModelError(f"contract_type is not registered for dashboard read models: {contract_type!r}")
    return contract_type


def _expect_list(payload: Mapping[str, Any], field: str) -> None:
    if not isinstance(payload.get(field), list):
        raise DashboardReadModelError(f"{field} must be a JSON array")


def _scan_for_secret_like_values(value: Any, *, path: str = "$", parent_key: str | None = None) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if SECRET_KEY_RE.search(key_text) and child not in (None, "", [], {}):
                raise DashboardReadModelError(f"secret-like field is not allowed in dashboard summary: {child_path}")
            _scan_for_secret_like_values(child, path=child_path, parent_key=key_text)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_secret_like_values(child, path=f"{path}[{index}]", parent_key=parent_key)
        return
    if isinstance(value, str) and SECRET_VALUE_RE.search(value):
        raise DashboardReadModelError(f"secret-like value is not allowed in dashboard summary: {path}")


def validate_dashboard_read_model(
    payload: Mapping[str, Any],
    *,
    expected_contract_type: str | None = None,
    now: datetime | None = None,
) -> str:
    """Validate the common dashboard read-model envelope.

    The function returns the validated contract type.  It intentionally checks
    only common storage/envelope safety rules; contract-specific semantics remain
    owned by the producer that understands the source evidence.
    """

    if not isinstance(payload, Mapping):
        raise DashboardReadModelError("dashboard read model must be a JSON object")
    missing = [field for field in REQUIRED_ENVELOPE_FIELDS if field not in payload]
    if missing:
        raise DashboardReadModelError("missing required dashboard read-model fields: " + ", ".join(missing))

    contract_type = _safe_contract_type(str(payload["contract_type"]))
    if expected_contract_type is not None and contract_type != _safe_contract_type(expected_contract_type):
        raise DashboardReadModelError(
            f"contract_type {contract_type!r} does not match expected contract {expected_contract_type!r}"
        )

    for field in ("source_system", "status", "summary", "schema_ref"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise DashboardReadModelError(f"{field} must be a non-empty string")

    if "severity" in payload and payload["severity"] not in (None, "") and payload["severity"] not in SEVERITY_VALUES:
        raise DashboardReadModelError(f"severity must be one of {sorted(SEVERITY_VALUES)}")
    if not isinstance(payload["chart_payload"], (dict, list)):
        raise DashboardReadModelError("chart_payload must be a JSON object or array")
    for field in ("profile_refs", "issue_refs", "diagnostic_refs", "lineage_refs"):
        _expect_list(payload, field)
    if not isinstance(payload["freshness"], Mapping):
        raise DashboardReadModelError("freshness must be a JSON object")

    schema_version = payload["schema_version"]
    if not isinstance(schema_version, int) or schema_version < 1:
        raise DashboardReadModelError("schema_version must be a positive integer")

    generated_at = _parse_utc_timestamp(str(payload["generated_at_utc"]), field="generated_at_utc")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if generated_at > current_time + CLOCK_SKEW:
        raise DashboardReadModelError("generated_at_utc is in the future beyond accepted clock skew")

    schema_ref = str(payload["schema_ref"])
    expected_schema_suffix = f"06_dashboard_cache/schemas/{contract_type}.schema.json"
    if schema_ref != contract_type and not schema_ref.endswith(expected_schema_suffix):
        raise DashboardReadModelError(
            "schema_ref must be the contract type or the accepted storage schema path for the contract"
        )

    _scan_for_secret_like_values(payload)
    return contract_type


def common_dashboard_schema(contract_type: str) -> dict[str, Any]:
    """Return a minimal JSON Schema for the common dashboard envelope."""

    contract_type = _safe_contract_type(contract_type)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"storage://trading-storage/06_dashboard_cache/schemas/{contract_type}.schema.json",
        "title": contract_type,
        "type": "object",
        "required": list(REQUIRED_ENVELOPE_FIELDS),
        "additionalProperties": True,
        "properties": {
            "contract_type": {"const": contract_type},
            "schema_version": {"type": "integer", "minimum": 1},
            "generated_at_utc": {"type": "string", "format": "date-time"},
            "source_system": {"type": "string", "minLength": 1},
            "status": {"type": "string", "minLength": 1},
            "severity": {"enum": sorted(SEVERITY_VALUES) + [None, ""]},
            "summary": {"type": "string", "minLength": 1},
            "chart_payload": {"type": ["object", "array"]},
            "profile_refs": {"type": "array"},
            "issue_refs": {"type": "array"},
            "diagnostic_refs": {"type": "array"},
            "lineage_refs": {"type": "array"},
            "freshness": {"type": "object"},
            "schema_ref": {"type": "string", "minLength": 1},
        },
    }


def _write_atomic_json(path: Path, payload: Mapping[str, Any]) -> bytes:
    content = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=f".{path.name}.") as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)
    return content


def _read_json_object(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _snapshot_state_hash(payload: Mapping[str, Any]) -> str:
    """Hash dashboard state while excluding volatile materialization time.

    ``generated_at_utc`` changes on every refresh and should keep
    ``latest.json`` current, but it should not create a new timestamped
    snapshot when the owner-facing state did not change.
    """

    stable_payload = dict(payload)
    stable_payload.pop("generated_at_utc", None)
    return "sha256:" + hashlib.sha256(canonical_json_bytes(stable_payload)).hexdigest()


def _storage_uri(storage_root: Path, path: Path) -> str:
    return "storage://trading-storage/" + str(path.relative_to(storage_root)).replace("\\", "/")


def materialize_dashboard_read_model(
    payload: Mapping[str, Any],
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    expected_contract_type: str | None = None,
    now: datetime | None = None,
) -> MaterializedDashboardReadModel:
    """Validate and materialize one dashboard read-model snapshot.

    The validated snapshot is written first, then ``latest.json`` is replaced
    atomically, then a compact JSONL index row is appended.
    """

    storage_root = Path(storage_root)
    contract_type = validate_dashboard_read_model(payload, expected_contract_type=expected_contract_type, now=now)
    compact = _compact_timestamp(str(payload["generated_at_utc"]))
    parsed = _parse_utc_timestamp(str(payload["generated_at_utc"]), field="generated_at_utc")

    snapshot_path = (
        storage_root
        / DASHBOARD_ROOT
        / "read_models"
        / contract_type
        / "snapshots"
        / parsed.strftime("%Y")
        / parsed.strftime("%m")
        / parsed.strftime("%d")
        / f"{compact}.json"
    )
    latest_path = storage_root / DASHBOARD_ROOT / "read_models" / contract_type / "latest.json"
    schema_path = storage_root / DASHBOARD_ROOT / "schemas" / f"{contract_type}.schema.json"
    index_path = storage_root / INDEX_PATH

    if not schema_path.exists():
        _write_atomic_json(schema_path, common_dashboard_schema(contract_type))

    payload_to_write: Mapping[str, Any] = payload
    if str(payload.get("contract_type")) != contract_type:
        normalized_payload = dict(payload)
        normalized_payload["contract_type"] = contract_type
        schema_ref = str(normalized_payload.get("schema_ref") or "")
        normalized_payload["schema_ref"] = schema_ref.replace(str(payload.get("contract_type")), contract_type)
        payload_to_write = normalized_payload

    content = canonical_json_bytes(payload_to_write)
    content_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    state_hash = _snapshot_state_hash(payload_to_write)
    latest_payload = _read_json_object(latest_path)
    latest_state_hash = _snapshot_state_hash(latest_payload) if latest_payload is not None else None
    write_snapshot = latest_state_hash != state_hash

    if write_snapshot:
        snapshot_content = _write_atomic_json(snapshot_path, payload_to_write)
        latest_content = _write_atomic_json(latest_path, payload_to_write)
        if latest_content != snapshot_content:
            raise DashboardReadModelError("latest.json content diverged from validated snapshot")
        byte_count = len(snapshot_content)
        storage_uri = _storage_uri(storage_root, snapshot_path)
        write_mode = "snapshot_and_latest"
    else:
        latest_content = _write_atomic_json(latest_path, payload_to_write)
        byte_count = len(latest_content)
        storage_uri = _storage_uri(storage_root, latest_path)
        write_mode = "latest_only_state_unchanged"

    index_row = {
        "contract_type": contract_type,
        "schema_version": payload["schema_version"],
        "generated_at_utc": payload["generated_at_utc"],
        "indexed_at_utc": now_utc(),
        "latest_uri": _storage_uri(storage_root, latest_path),
        "snapshot_uri": _storage_uri(storage_root, snapshot_path),
        "schema_uri": _storage_uri(storage_root, schema_path),
        "content_hash_sha256": content_hash,
        "snapshot_state_hash_sha256": state_hash,
        "byte_count": byte_count,
        "source_system": payload["source_system"],
        "status": payload["status"],
        "severity": payload.get("severity"),
        "snapshot_written": write_snapshot,
        "index_written": write_snapshot,
        "write_mode": write_mode,
    }
    if write_snapshot:
        append_text_locked(index_path, json.dumps(index_row, sort_keys=True) + "\n")

    return MaterializedDashboardReadModel(
        contract_type=contract_type,
        latest_path=latest_path,
        snapshot_path=snapshot_path,
        schema_path=schema_path,
        index_path=index_path,
        content_hash=content_hash,
        snapshot_state_hash=state_hash,
        byte_count=byte_count,
        generated_at_utc=str(payload["generated_at_utc"]),
        storage_uri=storage_uri,
        snapshot_written=write_snapshot,
        index_written=write_snapshot,
        write_mode=write_mode,
        index_row=index_row,
    )
