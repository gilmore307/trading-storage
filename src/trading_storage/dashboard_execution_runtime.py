"""Execution runtime status dashboard read-model producer.

This producer exposes the execution-owned realtime trading runtime status
through the storage/dashboard read-model boundary. Dashboard clients then use
the existing read-model WebSocket stream instead of polling execution directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

EXECUTION_RUNTIME_STATUS_CONTRACT = "execution_realtime_trading_runtime_status"
EXECUTION_RUNTIME_STATUS_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{EXECUTION_RUNTIME_STATUS_CONTRACT}.schema.json"
DEFAULT_STALE_AFTER_SECONDS = 120


def _default_storage_root() -> Path:
    explicit = os.environ.get("TRADING_STORAGE_FILES_ROOT")
    if explicit:
        return Path(explicit)
    root = Path(os.environ.get("TRADING_STORAGE_ROOT", "/root/projects/trading-storage"))
    return root if root.name == "storage" else root / "storage"


DEFAULT_STORAGE_ROOT = _default_storage_root()
DEFAULT_EXECUTION_STATUS_PATH = Path(
    os.environ.get(
        "TRADING_EXECUTION_RUNTIME_STATUS_PATH",
        str(DEFAULT_STORAGE_ROOT / "04_execution_artifacts/runtime/realtime_trading_runtime/runtime_status.json"),
    )
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _path_updated_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return None


def _status_payload(status_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    payload = _load_json(status_path)
    updated_at = _path_updated_at(status_path)
    if payload is None or payload.get("contract_type") != EXECUTION_RUNTIME_STATUS_CONTRACT:
        return None, updated_at
    return payload, updated_at


def build_execution_runtime_status_read_model(
    *,
    status_path: Path = DEFAULT_EXECUTION_STATUS_PATH,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the dashboard read-model envelope for execution runtime readiness."""

    generated_at_utc = generated_at_utc or now_utc()
    runtime_status, latest_updated_at = _status_payload(Path(status_path))
    if runtime_status is None:
        chart_payload = {
            "mode": "missing_runtime_status",
            "runtime_status": "not_available",
            "next_gate": "run_execution_realtime_runtime_check",
            "latest_status_path": str(status_path),
            "latest_updated_at_utc": latest_updated_at,
            "websocket_latest_route": f"/ws/read-models/{EXECUTION_RUNTIME_STATUS_CONTRACT}/latest",
            "safety": {
                "provider_calls_performed": 0,
                "model_activation_performed": False,
                "broker_order_construction_performed": False,
                "broker_calls_performed": 0,
                "account_mutation_performed": False,
            },
        }
        return {
            "contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT,
            "schema_version": 1,
            "generated_at_utc": generated_at_utc,
            "source_system": "trading-storage",
            "status": "not_available",
            "severity": "medium",
            "summary": "Execution realtime trading runtime status has not been materialized yet.",
            "chart_payload": chart_payload,
            "profile_refs": [{"registry_ref": "EXECUTION_REALTIME_TRADING_RUNTIME_STATUS", "field": "contract_type"}],
            "issue_refs": [{"issue_type": "missing_execution_runtime_status", "status": "open", "severity": "medium"}],
            "diagnostic_refs": [{"ref_type": "execution_runtime_status_path", "path": str(status_path), "included": False}],
            "lineage_refs": [{"contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT, "included": False}],
            "freshness": {"class": "execution_runtime_status_snapshot", "status": "missing", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
            "schema_ref": EXECUTION_RUNTIME_STATUS_SCHEMA_REF,
        }

    provider_calls = int(runtime_status.get("provider_calls_performed") or 0)
    broker_calls = int(runtime_status.get("broker_calls_performed") or 0)
    model_activation = bool(runtime_status.get("model_activation_performed"))
    order_construction = bool(runtime_status.get("broker_order_construction_performed"))
    account_mutation = bool(runtime_status.get("account_mutation_performed"))
    allowed_actions = runtime_status.get("allowed_actions") if isinstance(runtime_status.get("allowed_actions"), Mapping) else {}
    safety_violation = broker_calls > 0 or account_mutation or allowed_actions.get("broker_execution_allowed") is True
    status = str(runtime_status.get("runtime_status") or "unknown")
    severity = "critical" if safety_violation else "info" if status == "waiting_for_promoted_model" else "medium"
    chart_payload = {
        "mode": "runtime_readiness",
        "runtime_status": status,
        "next_gate": runtime_status.get("next_gate"),
        "active_model_pointer": runtime_status.get("active_model_pointer"),
        "interfaces_connected": runtime_status.get("interfaces_connected"),
        "allowed_actions": allowed_actions,
        "required_runtime_inputs": runtime_status.get("required_runtime_inputs"),
        "latest_status_path": str(status_path),
        "latest_updated_at_utc": latest_updated_at,
        "websocket_latest_route": f"/ws/read-models/{EXECUTION_RUNTIME_STATUS_CONTRACT}/latest",
        "safety": {
            "provider_calls_performed": provider_calls,
            "model_activation_performed": model_activation,
            "broker_order_construction_performed": order_construction,
            "broker_calls_performed": broker_calls,
            "account_mutation_performed": account_mutation,
        },
    }
    summary = (
        "Execution realtime runtime is waiting for a promoted active model pointer."
        if status == "waiting_for_promoted_model"
        else f"Execution realtime runtime status is {status}."
    )
    return {
        "contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": "unsafe" if safety_violation else status,
        "severity": severity,
        "summary": summary,
        "chart_payload": chart_payload,
        "profile_refs": [{"registry_ref": "EXECUTION_REALTIME_TRADING_RUNTIME_STATUS", "field": "contract_type"}],
        "issue_refs": [{"issue_type": "execution_runtime_safety_violation", "status": "open", "severity": "critical"}] if safety_violation else [],
        "diagnostic_refs": [{"ref_type": "execution_runtime_status_path", "path": str(status_path), "included": True}],
        "lineage_refs": [{"contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT, "path": str(status_path), "included": True}],
        "freshness": {"class": "execution_runtime_status_snapshot", "status": "fresh", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
        "schema_ref": EXECUTION_RUNTIME_STATUS_SCHEMA_REF,
    }


def refresh_execution_runtime_status_read_model(
    *,
    storage_root: Path = Path("storage"),
    status_path: Path = DEFAULT_EXECUTION_STATUS_PATH,
) -> dict[str, Any]:
    storage_root.mkdir(parents=True, exist_ok=True)
    payload = build_execution_runtime_status_read_model(status_path=status_path)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=EXECUTION_RUNTIME_STATUS_CONTRACT)
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT,
        "materialized": materialized.index_row,
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


def write_execution_runtime_status_read_model(payload: Mapping[str, Any], *, output: TextIO) -> None:
    json.dump(dict(payload), output, indent=2, sort_keys=True)
    output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or refresh execution realtime runtime status read model.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--status-path", type=Path, default=DEFAULT_EXECUTION_STATUS_PATH)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    if args.refresh:
        json.dump(
            refresh_execution_runtime_status_read_model(storage_root=args.storage_root, status_path=args.status_path),
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    write_execution_runtime_status_read_model(
        build_execution_runtime_status_read_model(status_path=args.status_path),
        output=sys.stdout,
    )
    return 0


__all__ = [
    "EXECUTION_RUNTIME_STATUS_CONTRACT",
    "build_execution_runtime_status_read_model",
    "refresh_execution_runtime_status_read_model",
    "write_execution_runtime_status_read_model",
]
