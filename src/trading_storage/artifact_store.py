"""Filesystem-backed artifact payload helpers for the storage boundary.

This is the first concrete storage implementation slice: canonical JSON payloads
are written under an ignored local storage root, while callers receive an
`artifact_ref`-shaped metadata record suitable for manager SQL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_RETENTION_POLICY = "development_retained_until_promoted"


class StorageArtifactError(ValueError):
    """Raised when a storage artifact payload is invalid or unsafe."""


@dataclass(frozen=True)
class StoredArtifact:
    artifact_ref: dict[str, Any]
    local_path: Path
    content_hash: str
    byte_size: int


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _safe_token(value: str, *, field: str) -> str:
    if (
        not value
        or value == "."
        or any(separator in value for separator in ("/", "\\"))
        or ".." in Path(value).parts
    ):
        raise StorageArtifactError(f"unsafe {field}: {value!r}")
    return value


def _artifact_path(storage_root: Path, artifact_type: str, artifact_id: str, suffix: str) -> Path:
    safe_type = _safe_token(artifact_type, field="artifact_type")
    safe_id = _safe_token(artifact_id, field="artifact_id")
    return storage_root / "artifacts" / safe_type / f"{safe_id}.{suffix}"


def store_json_artifact(
    payload: Mapping[str, Any],
    *,
    artifact_id: str,
    artifact_type: str,
    producer_repo: str,
    producer_workflow: str,
    manifest_id: str,
    schema_ref: str,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    produced_at: str | None = None,
    visibility_time: str | None = None,
    retention_policy: str = DEFAULT_RETENTION_POLICY,
    row_count: int | None = None,
    overwrite_same_hash: bool = True,
) -> StoredArtifact:
    """Store canonical JSON payload bytes and return artifact_ref metadata."""

    for field_name, value in {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "producer_repo": producer_repo,
        "producer_workflow": producer_workflow,
        "manifest_id": manifest_id,
        "schema_ref": schema_ref,
    }.items():
        if not value:
            raise StorageArtifactError(f"{field_name} is required")
    content = canonical_json_bytes(payload)
    content_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    path = _artifact_path(storage_root, artifact_type, artifact_id, "json")
    if path.exists():
        existing_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if existing_hash != content_hash or not overwrite_same_hash:
            raise StorageArtifactError(f"artifact already exists with different content: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    uri = "storage://trading-storage/" + str(path.relative_to(storage_root)).replace("\\", "/")
    timestamp = produced_at or now_utc()
    artifact_ref = {
        "contract_type": "artifact_ref",
        "schema_version": 1,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "producer_repo": producer_repo,
        "producer_workflow": producer_workflow,
        "produced_at": timestamp,
        "storage_backend": "filesystem",
        "storage_uri": uri,
        "content_format": "json",
        "schema_ref": schema_ref,
        "content_hash_sha256": content_hash,
        "mutability": "immutable",
        "visibility_time": visibility_time or timestamp,
        "retention_policy": retention_policy,
        "manifest_id": manifest_id,
        "byte_count": len(content),
        "row_count": row_count,
    }
    return StoredArtifact(artifact_ref=artifact_ref, local_path=path, content_hash=content_hash, byte_size=len(content))


def store_completion_receipt_payload(
    receipt: Mapping[str, Any],
    *,
    request_id: str,
    run_id: str,
    producer_repo: str,
    workflow_id: str,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
) -> StoredArtifact:
    """Store a component completion receipt as a storage-owned JSON artifact."""

    if not isinstance(receipt, Mapping):
        raise StorageArtifactError("receipt must be a JSON object")
    if not request_id:
        raise StorageArtifactError("request_id is required")
    if not run_id:
        raise StorageArtifactError("run_id is required")
    artifact_id = f"art_receipt_{_safe_token(run_id, field='run_id')}"
    manifest_id = f"manifest_{_safe_token(run_id, field='run_id')}"
    payload = {
        "contract_type": "component_completion_receipt_payload",
        "schema_version": 1,
        "request_id": request_id,
        "run_id": run_id,
        "producer_repo": producer_repo,
        "workflow_id": workflow_id,
        "receipt": dict(receipt),
    }
    return store_json_artifact(
        payload,
        artifact_id=artifact_id,
        artifact_type="component_completion_receipt",
        producer_repo=producer_repo,
        producer_workflow=workflow_id,
        manifest_id=manifest_id,
        schema_ref="component_completion_receipt_payload",
        storage_root=storage_root,
    )
