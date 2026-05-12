"""Current system-status dashboard read-model producer.

This module builds the storage-owned `current_system_status_summary` payload
from read-only infrastructure observations: host resource posture, systemd
service/timer state, dashboard read-model freshness, and public dashboard API
route configuration.  It does not call providers, dispatch manager work,
activate models, submit broker orders, mutate accounts, or write storage by
itself.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, TextIO

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

CURRENT_SYSTEM_STATUS_CONTRACT = "current_system_status_summary"
CURRENT_SYSTEM_STATUS_SCHEMA_REF = f"storage/dashboard/schemas/{CURRENT_SYSTEM_STATUS_CONTRACT}.schema.json"
HISTORICAL_TASK_PROGRESS_CONTRACT = "historical_task_progress_summary"
DEFAULT_STALE_AFTER_SECONDS = 120

SYSTEMD_UNITS = (
    "trading-manager-historical-scheduler.service",
    "trading-storage-dashboard-read-model-refresh.timer",
    "trading-storage-dashboard-read-model-refresh.service",
)


def _run_text(argv: tuple[str, ...], *, timeout: float = 3.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return completed.returncode, completed.stdout.strip() or completed.stderr.strip()


def _systemd_unit(unit: str) -> dict[str, Any]:
    active_rc, active = _run_text(("systemctl", "is-active", unit))
    enabled_rc, enabled = _run_text(("systemctl", "is-enabled", unit))
    substate_rc, substate = _run_text(("systemctl", "show", unit, "-p", "SubState", "--value"))
    return {
        "unit": unit,
        "active_state": active if active_rc == 0 else active or "unknown",
        "enabled_state": enabled if enabled_rc == 0 else enabled or "unknown",
        "substate": substate if substate_rc == 0 else "unknown",
        "healthy": active == "active" or (unit.endswith(".service") and active in {"inactive", "activating"}),
    }


def _host_resources(storage_root: Path) -> dict[str, Any]:
    stat = shutil.disk_usage(storage_root)
    load_average = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    memory: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                memory[key] = int(raw.strip().split()[0])
    except OSError:
        pass
    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": round(time.monotonic()),
        "load_average_1m": round(load_average[0], 2),
        "load_average_5m": round(load_average[1], 2),
        "load_average_15m": round(load_average[2], 2),
        "memory_total_mb": round(memory.get("MemTotal", 0) / 1024),
        "memory_available_mb": round(memory.get("MemAvailable", 0) / 1024),
        "storage_total_gb": round(stat.total / (1024**3), 2),
        "storage_available_gb": round(stat.free / (1024**3), 2),
    }


def _read_model_freshness(storage_root: Path, contract_type: str, *, now_epoch: float) -> dict[str, Any]:
    latest_path = storage_root / "dashboard" / "read_models" / contract_type / "latest.json"
    if not latest_path.exists():
        return {"contract_type": contract_type, "exists": False, "status": "missing", "age_seconds": None}
    age_seconds = round(now_epoch - latest_path.stat().st_mtime)
    payload: Mapping[str, Any] = {}
    try:
        loaded = json.loads(latest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, Mapping):
            payload = loaded
    except (OSError, json.JSONDecodeError):
        return {"contract_type": contract_type, "exists": True, "status": "unreadable", "age_seconds": age_seconds}
    stale_after = int((payload.get("freshness") or {}).get("stale_after_seconds") or DEFAULT_STALE_AFTER_SECONDS)
    status = "fresh" if age_seconds <= stale_after else "stale"
    return {
        "contract_type": contract_type,
        "exists": True,
        "status": status,
        "age_seconds": age_seconds,
        "generated_at_utc": payload.get("generated_at_utc"),
        "payload_status": payload.get("status"),
        "stale_after_seconds": stale_after,
    }


def build_current_system_status_summary(*, storage_root: Path, generated_at_utc: str | None = None) -> dict[str, Any]:
    generated_at_utc = generated_at_utc or now_utc()
    now_epoch = time.time()
    host = _host_resources(storage_root)
    services = [_systemd_unit(unit) for unit in SYSTEMD_UNITS]
    read_models = [
        _read_model_freshness(storage_root, CURRENT_SYSTEM_STATUS_CONTRACT, now_epoch=now_epoch),
        _read_model_freshness(storage_root, HISTORICAL_TASK_PROGRESS_CONTRACT, now_epoch=now_epoch),
    ]
    unhealthy_services = [service["unit"] for service in services if not service["healthy"]]
    stale_models = [model["contract_type"] for model in read_models if model["status"] not in {"fresh", "missing"}]
    severity = "info" if not unhealthy_services and not stale_models else "medium"
    status = "healthy" if severity == "info" else "degraded"
    summary = (
        "Infrastructure status is healthy; dashboard API, refresh timer, and observed services are available."
        if status == "healthy"
        else "Infrastructure status is degraded; inspect service or read-model freshness details."
    )
    return {
        "contract_type": CURRENT_SYSTEM_STATUS_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": status,
        "severity": severity,
        "summary": summary,
        "chart_payload": {
            "server": host,
            "api": {
                "http_latest_route": "/api/read-models/<contract_type>/latest",
                "websocket_latest_route": "/ws/read-models/<contract_type>/latest",
                "status": "configured",
            },
            "services": services,
            "read_models": read_models,
            "refresh": {
                "timer_unit": "trading-storage-dashboard-read-model-refresh.timer",
                "cadence_seconds": 30,
                "status": next((service["active_state"] for service in services if service["unit"].endswith(".timer")), "unknown"),
            },
        },
        "profile_refs": [
            {"registry_ref": "CURRENT_SYSTEM_STATUS_SUMMARY", "field": "contract_type"},
            {"registry_ref": "DASHBOARD_READ_MODEL_COMMON_ENVELOPE", "field": "common_envelope"},
        ],
        "issue_refs": [
            {"issue_type": "systemd_unit_not_healthy", "unit": unit, "severity": "medium"} for unit in unhealthy_services
        ],
        "diagnostic_refs": [
            {"ref_type": "systemd_units", "count": len(services)},
            {"ref_type": "dashboard_read_model_freshness", "count": len(read_models)},
        ],
        "lineage_refs": [
            {"contract_type": "systemd_unit_status", "included": True},
            {"contract_type": "host_resource_snapshot", "included": True},
            {"contract_type": "dashboard_read_model_latest_files", "included": True},
        ],
        "freshness": {"class": "infrastructure_status_snapshot", "status": "fresh", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
        "schema_ref": CURRENT_SYSTEM_STATUS_SCHEMA_REF,
    }


def refresh_current_system_status_read_model(*, storage_root: Path = Path("storage")) -> dict[str, Any]:
    payload = build_current_system_status_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=CURRENT_SYSTEM_STATUS_CONTRACT)
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": CURRENT_SYSTEM_STATUS_CONTRACT,
        "materialized": materialized.index_row,
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


def write_current_system_status_summary(payload: Mapping[str, Any], *, output: TextIO) -> None:
    json.dump(dict(payload), output, indent=2, sort_keys=True)
    output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or refresh current_system_status_summary from read-only infrastructure observations.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--refresh", action="store_true", help="Materialize the summary into storage/dashboard instead of printing only.")
    args = parser.parse_args(argv)
    if args.refresh:
        json.dump(refresh_current_system_status_read_model(storage_root=args.storage_root), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    write_current_system_status_summary(build_current_system_status_summary(storage_root=args.storage_root), output=sys.stdout)
    return 0


__all__ = [
    "CURRENT_SYSTEM_STATUS_CONTRACT",
    "build_current_system_status_summary",
    "refresh_current_system_status_read_model",
    "write_current_system_status_summary",
]
