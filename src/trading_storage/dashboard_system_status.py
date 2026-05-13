"""Current system-status dashboard read-model producer.

This module builds the storage-owned `current_system_status_summary` payload
from read-only infrastructure observations: host resource posture, systemd
service/timer state, source output file freshness, and provider API local
configuration/runtime status.  It does not call providers, dispatch manager work,
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
DEFAULT_TRADING_MANAGER_ROOT = Path(os.environ.get("TRADING_MANAGER_ROOT", "/root/projects/trading-manager"))

SYSTEMD_UNITS = (
    "trading-manager-historical-scheduler.service",
    "trading-storage-dashboard-read-model-refresh.timer",
    "trading-storage-dashboard-read-model-refresh.service",
)
PROVIDER_APIS = (
    {"alias": "alpaca", "name": "Alpaca Market Data API", "kind": "market_data"},
    {"alias": "okx", "name": "OKX Market Data API", "kind": "crypto_market_data"},
    {"alias": "thetadata", "name": "ThetaData Options API", "kind": "options_data"},
)
THETADATA_TERMINAL_HOST = "127.0.0.1"
THETADATA_TERMINAL_PORT = 25503


def _read_cpu_totals() -> tuple[int, int] | None:
    """Return Linux aggregate CPU total and idle jiffies from /proc/stat."""

    try:
        first_line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    parts = first_line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(value) for value in parts[1:]]
    except ValueError:
        return None
    if len(values) < 5:
        return None
    idle = values[3] + values[4]
    total = sum(values)
    return total, idle


def _read_network_totals() -> tuple[int, int] | None:
    """Return non-loopback receive/transmit byte counters from /proc/net/dev."""

    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
    except OSError:
        return None
    receive_bytes = 0
    transmit_bytes = 0
    for line in lines:
        if ":" not in line:
            continue
        iface, raw_values = line.split(":", 1)
        if iface.strip() == "lo":
            continue
        fields = raw_values.split()
        if len(fields) < 16:
            continue
        try:
            receive_bytes += int(fields[0])
            transmit_bytes += int(fields[8])
        except ValueError:
            continue
    return receive_bytes, transmit_bytes


def _sample_live_resource_usage(*, interval_seconds: float = 0.1) -> dict[str, float]:
    cpu_before = _read_cpu_totals()
    net_before = _read_network_totals()
    time.sleep(interval_seconds)
    cpu_after = _read_cpu_totals()
    net_after = _read_network_totals()
    usage: dict[str, float] = {}
    if cpu_before and cpu_after:
        total_delta = cpu_after[0] - cpu_before[0]
        idle_delta = cpu_after[1] - cpu_before[1]
        if total_delta > 0:
            usage["cpu_usage_percent"] = round(max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100)), 1)
    if net_before and net_after and interval_seconds > 0:
        download_delta = max(0, net_after[0] - net_before[0])
        upload_delta = max(0, net_after[1] - net_before[1])
        usage["network_download_kbps"] = round((download_delta / 1024) / interval_seconds, 1)
        usage["network_upload_kbps"] = round((upload_delta / 1024) / interval_seconds, 1)
    return usage


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
    live_usage = _sample_live_resource_usage()
    memory: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                memory[key] = int(raw.strip().split()[0])
    except OSError:
        pass
    memory_total_mb = round(memory.get("MemTotal", 0) / 1024)
    memory_available_mb = round(memory.get("MemAvailable", 0) / 1024)
    memory_usage_percent = round((memory_total_mb - memory_available_mb) / memory_total_mb * 100, 1) if memory_total_mb else 0.0
    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": round(time.monotonic()),
        "load_average_1m": round(load_average[0], 2),
        "load_average_5m": round(load_average[1], 2),
        "load_average_15m": round(load_average[2], 2),
        "cpu_usage_percent": live_usage.get("cpu_usage_percent", 0.0),
        "memory_usage_percent": memory_usage_percent,
        "memory_total_mb": memory_total_mb,
        "memory_available_mb": memory_available_mb,
        "network_download_kbps": live_usage.get("network_download_kbps", 0.0),
        "network_upload_kbps": live_usage.get("network_upload_kbps", 0.0),
        "storage_total_gb": round(stat.total / (1024**3), 2),
        "storage_available_gb": round(stat.free / (1024**3), 2),
    }


def _secret_alias_configured(alias: str) -> bool:
    secret_root = Path(os.environ.get("TRADING_SECRET_ROOT", "/root/secrets"))
    if (secret_root / f"{alias}.json").exists():
        return True
    registry_path = secret_root / "registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(registry, Mapping) and alias in registry


def _local_port_open(host: str, port: int, *, timeout_seconds: float = 0.1) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _provider_api_statuses() -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for provider in PROVIDER_APIS:
        alias = str(provider["alias"])
        configured = _secret_alias_configured(alias)
        status = "configured" if configured else "not_configured"
        healthy = configured
        if alias == "thetadata" and configured:
            terminal_online = _local_port_open(THETADATA_TERMINAL_HOST, THETADATA_TERMINAL_PORT)
            status = "local_service_online" if terminal_online else "local_service_offline"
            healthy = terminal_online
        statuses.append(
            {
                "name": provider["name"],
                "kind": provider["kind"],
                "status": status,
                "healthy": healthy,
            }
        )
    return statuses


def _mtime_utc(path: Path) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))


def _latest_json_timestamp(payload: Mapping[str, Any]) -> str | None:
    for key in ("updated_utc", "generated_utc", "generated_at_utc", "last_tick_completed_utc", "timestamp_utc"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value.replace("+00:00", "Z")
    return None


def _latest_jsonl_timestamp(path: Path) -> str | None:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            return _latest_json_timestamp(payload)
    return None


def _source_output_status(path: Path, *, label: str, kind: str, now_epoch: float) -> dict[str, Any]:
    if not path.exists():
        return {
            "label": label,
            "kind": kind,
            "status": "missing",
            "exists": False,
            "age_seconds": None,
            "latest_updated_at_utc": None,
        }
    age_seconds = round(now_epoch - path.stat().st_mtime)
    latest_updated_at_utc = _mtime_utc(path)
    if path.suffix.lower() == ".jsonl":
        latest_updated_at_utc = _latest_jsonl_timestamp(path) or latest_updated_at_utc
    elif path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "label": label,
                "kind": kind,
                "status": "unreadable",
                "exists": True,
                "age_seconds": age_seconds,
                "latest_updated_at_utc": latest_updated_at_utc,
            }
        if isinstance(payload, Mapping):
            latest_updated_at_utc = _latest_json_timestamp(payload) or latest_updated_at_utc
    return {
        "label": label,
        "kind": kind,
        "status": "available",
        "exists": True,
        "age_seconds": age_seconds,
        "latest_updated_at_utc": latest_updated_at_utc,
    }


def _latest_matching_file(root: Path, pattern: str) -> Path | None:
    try:
        matches = [path for path in root.glob(pattern) if path.is_file()]
    except OSError:
        return None
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _dashboard_source_outputs(*, trading_manager_root: Path, now_epoch: float) -> list[dict[str, Any]]:
    runtime_root = trading_manager_root / "storage" / "runtime"
    output_specs: list[tuple[str, str, Path | None]] = [
        ("Historical Scheduler State", "manager_scheduler_state", runtime_root / "historical_scheduler_state.json"),
        ("Scheduler Decision Log", "manager_scheduler_decision_log", runtime_root / "historical_scheduler_decisions.jsonl"),
        ("Active Workflow State", "manager_workflow_state", runtime_root / "model_training_workflow_state.json"),
        (
            "Latest Stage Coverage Output",
            "manager_stage_coverage",
            _latest_matching_file(runtime_root / "stage_coverage", "*.json"),
        ),
        (
            "Latest Stage Run Output",
            "manager_stage_run_dashboard",
            _latest_matching_file(runtime_root / "stage_run_dashboard", "*.json"),
        ),
    ]
    outputs: list[dict[str, Any]] = []
    for label, kind, path in output_specs:
        if path is None:
            outputs.append({"label": label, "kind": kind, "status": "missing", "exists": False, "age_seconds": None, "latest_updated_at_utc": None})
            continue
        outputs.append(_source_output_status(path, label=label, kind=kind, now_epoch=now_epoch))
    return outputs


def build_current_system_status_summary(*, storage_root: Path, generated_at_utc: str | None = None) -> dict[str, Any]:
    generated_at_utc = generated_at_utc or now_utc()
    now_epoch = time.time()
    host = _host_resources(storage_root)
    services = [_systemd_unit(unit) for unit in SYSTEMD_UNITS]
    source_outputs = _dashboard_source_outputs(trading_manager_root=DEFAULT_TRADING_MANAGER_ROOT, now_epoch=now_epoch)
    unhealthy_services = [service["unit"] for service in services if not service["healthy"]]
    missing_outputs = [output["label"] for output in source_outputs if output["status"] == "missing"]
    severity = "info" if not unhealthy_services and not missing_outputs else "medium"
    status = "healthy" if severity == "info" else "degraded"
    summary = (
        "Infrastructure status is healthy; refresh timer, provider API configuration, observed services, and dashboard source outputs are available."
        if status == "healthy"
        else "Infrastructure status is degraded; inspect service, provider API, or dashboard source output details."
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
            "apis": _provider_api_statuses(),
            "services": services,
            "source_outputs": source_outputs,
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
            {"ref_type": "dashboard_source_outputs", "count": len(source_outputs)},
        ],
        "lineage_refs": [
            {"contract_type": "systemd_unit_status", "included": True},
            {"contract_type": "host_resource_snapshot", "included": True},
            {"contract_type": "dashboard_source_output_files", "included": True},
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
