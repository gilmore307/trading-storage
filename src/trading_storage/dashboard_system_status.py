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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, TextIO

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

CURRENT_SYSTEM_STATUS_CONTRACT = "current_system_status_summary"
CURRENT_SYSTEM_STATUS_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{CURRENT_SYSTEM_STATUS_CONTRACT}.schema.json"
HISTORICAL_TASK_PROGRESS_CONTRACT = "historical_task_progress_summary"
DEFAULT_STALE_AFTER_SECONDS = 120
DEFAULT_TRADING_MANAGER_ROOT = Path(os.environ.get("TRADING_MANAGER_ROOT", "/root/projects/trading-manager"))


def _default_storage_root() -> Path:
    explicit = os.environ.get("TRADING_STORAGE_FILES_ROOT")
    if explicit:
        return Path(explicit)
    root = Path(os.environ.get("TRADING_STORAGE_ROOT", "/root/projects/trading-storage"))
    return root if root.name == "storage" else root / "storage"


DEFAULT_STORAGE_ROOT = _default_storage_root()
DEFAULT_MANAGER_STORAGE_ROOT = Path(os.environ.get("TRADING_MANAGER_STORAGE_ROOT", str(DEFAULT_STORAGE_ROOT / "02_control_plane")))
DEFAULT_SCHEDULER_ENV_PATH = Path("/etc/default/trading-manager-historical-scheduler")
DEFAULT_STORAGE_REFRESH_ENV_PATH = Path(os.environ.get("TRADING_STORAGE_REFRESH_ENV_PATH", "/etc/default/trading-storage-dashboard-read-model-refresh"))
DEFAULT_REFRESH_CADENCE_SECONDS = 60
DEFAULT_PROVIDER_STAGE_NEXT_LIMIT = 12
DEFAULT_PROVIDER_STAGE_MAX_WORKERS = 4
DEFAULT_MONTH_INGEST_WORKERS = 3
DEFAULT_MODEL_WORKERS = 1
DEFAULT_THROUGHPUT_WINDOW_MINUTES = 15
DEFAULT_PROVIDER_STAGE_LOAD_TARGET_PER_CPU = 0.70
DEFAULT_PROVIDER_STAGE_WORKER_MEMORY_MB = 512
DEFAULT_PROVIDER_STAGE_RESERVED_MEMORY_MB = 2048

SYSTEMD_UNIT_FALLBACKS = (
    "trading-dashboard-web.service",
    "trading-manager-historical-scheduler.service",
    "trading-data-te-calendar-refresh.service",
    "trading-execution-realtime-monitor-loop.service",
    "trading-storage-dashboard-read-model-refresh.service",
    "trading-data-te-calendar-refresh.timer",
    "trading-execution-realtime-runtime-check.service",
    "trading-storage-dashboard-read-model-refresh.timer",
    "trading-execution-realtime-runtime-check.timer",
    "trading-execution-realtime-runtime-check.path",
)
RETIRED_SYSTEMD_UNITS = frozenset()
FAILED_SYSTEMD_RESULTS = {
    "core-dump",
    "exit-code",
    "failed",
    "oom-kill",
    "protocol",
    "resources",
    "signal",
    "start-limit-hit",
    "timeout",
    "watchdog",
}
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


def _unit_kind(unit: str) -> str:
    return unit.rsplit(".", 1)[-1] if "." in unit else "unit"


def _unit_sort_key(unit: str) -> tuple[int, str]:
    try:
        return (SYSTEMD_UNIT_FALLBACKS.index(unit), unit)
    except ValueError:
        kind_rank = {"service": 10, "timer": 20, "path": 30}.get(_unit_kind(unit), 40)
        return (kind_rank, unit)


def _trading_systemd_unit_names() -> list[str]:
    rc, output = _run_text(("systemctl", "list-unit-files", "trading-*", "--no-legend", "--no-pager", "--plain"))
    units: list[str] = []
    if rc == 0:
        for line in output.splitlines():
            parts = line.split()
            if parts and parts[0].startswith("trading-") and "." in parts[0] and parts[0] not in RETIRED_SYSTEMD_UNITS:
                units.append(parts[0])
    if not units:
        units = list(SYSTEMD_UNIT_FALLBACKS)
    return sorted(set(units), key=_unit_sort_key)


def _systemd_properties(unit: str) -> dict[str, str]:
    rc, output = _run_text(
        (
            "systemctl",
            "show",
            unit,
            "-p",
            "ActiveState",
            "-p",
            "LoadState",
            "-p",
            "SubState",
            "-p",
            "Result",
            "-p",
            "Type",
            "-p",
            "UnitFileState",
        )
    )
    if rc != 0:
        return {}
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def _systemd_unit_is_healthy(
    *,
    unit_kind: str,
    unit_type: str,
    load_state: str,
    active_state: str,
    enabled_state: str,
    substate: str,
    result: str,
) -> bool:
    if load_state in {"bad-setting", "error", "not-found"}:
        return False
    if active_state == "failed" or result in FAILED_SYSTEMD_RESULTS:
        return False
    if active_state in {"active", "reloading"}:
        return True
    if active_state == "activating":
        if unit_kind == "service" and substate == "auto-restart" and result == "success":
            return True
        return substate != "auto-restart"
    if active_state == "inactive" and result in {"", "success"}:
        if unit_type == "oneshot":
            return True
        if enabled_state in {"disabled", "indirect", "static"}:
            return True
        if unit_kind in {"path", "timer"} and enabled_state == "disabled":
            return True
    return False


def _systemd_unit(unit: str) -> dict[str, Any]:
    properties = _systemd_properties(unit)
    active_state = properties.get("ActiveState") or "unknown"
    enabled_state = properties.get("UnitFileState") or "unknown"
    load_state = properties.get("LoadState") or "unknown"
    substate = properties.get("SubState") or "unknown"
    result = properties.get("Result") or "unknown"
    unit_type = properties.get("Type") or "unknown"
    unit_kind = _unit_kind(unit)
    return {
        "unit": unit,
        "unit_kind": unit_kind,
        "unit_type": unit_type,
        "load_state": load_state,
        "active_state": active_state,
        "enabled_state": enabled_state,
        "substate": substate,
        "result": result,
        "healthy": _systemd_unit_is_healthy(
            unit_kind=unit_kind,
            unit_type=unit_type,
            load_state=load_state,
            active_state=active_state,
            enabled_state=enabled_state,
            substate=substate,
            result=result,
        ),
    }


def _historical_scheduler_is_active(services: list[Mapping[str, Any]]) -> bool:
    return any(
        service.get("unit") == "trading-manager-historical-scheduler.service"
        and service.get("active_state") == "active"
        for service in services
    )


def _mark_source_outputs_not_started(source_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for output in source_outputs:
        updated = dict(output)
        if updated.get("status") == "missing" and not updated.get("exists"):
            updated["status"] = "not_started"
            updated["freshness_note"] = (
                "Historical training is stopped; this source output appears after the scheduler starts and records work."
            )
        marked.append(updated)
    return marked


def _mark_missing_event_outputs_waiting(source_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for output in source_outputs:
        updated = dict(output)
        if updated.get("status") == "missing" and not updated.get("exists") and updated.get("freshness_class") == "event_driven":
            updated["status"] = "not_recorded_yet"
            updated["freshness_note"] = (
                "Event-driven source output has not been recorded yet; it appears only after the relevant scheduler decision or stage output exists."
            )
        marked.append(updated)
    return marked


def _mark_parked_execution_outputs(
    source_outputs: list[dict[str, Any]],
    *,
    services: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    execution_output_kinds = {
        "execution_runtime_status",
        "execution_realtime_monitor_receipt",
        "execution_realtime_monitor_cycle",
    }
    execution_runtime_units = {
        "trading-execution-realtime-monitor-loop.service",
        "trading-execution-realtime-runtime-check.service",
        "trading-execution-realtime-runtime-check.timer",
        "trading-execution-realtime-runtime-check.path",
    }
    realtime_active = any(
        service.get("unit") in execution_runtime_units and service.get("active_state") == "active"
        for service in services
    )
    if realtime_active:
        return source_outputs
    marked: list[dict[str, Any]] = []
    for output in source_outputs:
        updated = dict(output)
        if updated.get("kind") in execution_output_kinds and updated.get("status") in {"available", "missing"}:
            updated["status"] = "parked"
            updated["freshness_note"] = (
                "Execution realtime services are not active; this is the last recorded artifact from the parked realtime path, "
                "not an expected live heartbeat."
            )
        marked.append(updated)
    return marked


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_int(values: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(values.get(key, "") or default)
    except ValueError:
        return default


def _env_bool(values: Mapping[str, str], key: str, default: bool) -> bool:
    raw = values.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _tail_jsonl(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    if raw and not raw.startswith("{") and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _historical_scheduler_runtime_throughput(
    *,
    values: Mapping[str, str],
    manager_storage_root: Path = DEFAULT_MANAGER_STORAGE_ROOT,
    window_minutes: int = DEFAULT_THROUGHPUT_WINDOW_MINUTES,
) -> dict[str, Any]:
    month_workers = _env_int(values, "TRADING_MANAGER_MONTH_INGEST_WORKERS", DEFAULT_MONTH_INGEST_WORKERS)
    model_workers = DEFAULT_MODEL_WORKERS
    total_workers = max(1, month_workers) + model_workers
    rows = _tail_jsonl(manager_storage_root / "runtime/historical_scheduler_decisions.jsonl")
    timed_rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        parsed = _parse_utc_timestamp(row.get("now_utc") or row.get("updated_utc") or row.get("generated_at_utc"))
        if parsed is not None:
            timed_rows.append((parsed, row))
    if not timed_rows:
        return {
            "status": "no_decision_log",
            "mode": "runtime_throughput",
            "month_ingest_worker_count": month_workers,
            "model_worker_count": model_workers,
            "total_worker_count": total_workers,
            "fold_month_count": 6,
            "month_ingest_rounds_per_fold": 2 if month_workers == 3 else None,
            "window_minutes": window_minutes,
            "executed_decision_count": 0,
            "decision_count": 0,
            "completion_rate_per_minute": 0.0,
            "max_completions_per_second": 0,
            "multi_completion_second_count": 0,
            "summary": f"Runtime topology is {month_workers} month-ingest workers plus {model_workers} model worker; no scheduler decision log is available yet.",
        }
    latest_at = max(ts for ts, _row in timed_rows)
    window_start = latest_at - timedelta(minutes=max(1, window_minutes))
    window_rows = [(ts, row) for ts, row in timed_rows if ts >= window_start]
    executed_rows = [(ts, row) for ts, row in window_rows if row.get("decision_status") == "executed"]
    second_counts: dict[str, int] = {}
    for ts, _row in executed_rows:
        key = ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        second_counts[key] = second_counts.get(key, 0) + 1
    if len(executed_rows) >= 2:
        span_seconds = max(1.0, (max(ts for ts, _ in executed_rows) - min(ts for ts, _ in executed_rows)).total_seconds())
    else:
        span_seconds = 60.0
    completion_rate = (len(executed_rows) / span_seconds) * 60.0
    max_per_second = max(second_counts.values()) if second_counts else 0
    multi_second_count = sum(1 for count in second_counts.values() if count >= 2)
    idle_decisions = sum(1 for _ts, row in window_rows if row.get("decision_status") not in {"executed", "ready"})
    return {
        "status": "active" if executed_rows else "observed_idle",
        "mode": "runtime_throughput",
        "month_ingest_worker_count": month_workers,
        "model_worker_count": model_workers,
        "total_worker_count": total_workers,
        "fold_month_count": 6,
        "month_ingest_rounds_per_fold": 2 if month_workers == 3 else None,
        "window_minutes": window_minutes,
        "window_start_utc": window_start.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "latest_decision_at_utc": latest_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "decision_count": len(window_rows),
        "executed_decision_count": len(executed_rows),
        "idle_or_blocked_decision_count": idle_decisions,
        "completion_rate_per_minute": round(completion_rate, 2),
        "max_completions_per_second": max_per_second,
        "multi_completion_second_count": multi_second_count,
        "active_worker_estimate": min(total_workers, max_per_second),
        "summary": (
            f"{month_workers} month-ingest workers plus {model_workers} model worker; "
            f"latest window completed {len(executed_rows)} decisions at {round(completion_rate, 2)} completions/min."
        ),
    }


def _historical_scheduler_parallelism(host: Mapping[str, Any], *, trading_manager_root: Path = DEFAULT_TRADING_MANAGER_ROOT) -> dict[str, Any]:
    repo_defaults = _read_env_file(trading_manager_root / "deploy/systemd/trading-manager-historical-scheduler.env")
    host_overrides = _read_env_file(DEFAULT_SCHEDULER_ENV_PATH)
    values = repo_defaults | host_overrides
    next_limit = _env_int(values, "TRADING_MANAGER_PROVIDER_STAGE_NEXT_LIMIT", DEFAULT_PROVIDER_STAGE_NEXT_LIMIT)
    max_workers = _env_int(values, "TRADING_MANAGER_PROVIDER_STAGE_MAX_WORKERS", DEFAULT_PROVIDER_STAGE_MAX_WORKERS)
    interval_seconds = _env_int(values, "TRADING_MANAGER_HISTORICAL_INTERVAL_SECONDS", 60)
    drain_max_steps = _env_int(values, "TRADING_MANAGER_DRAIN_MAX_STEPS", 50)
    drain_max_seconds = _env_int(values, "TRADING_MANAGER_DRAIN_MAX_SECONDS", 300)
    refresh_service_unit = values.get("TRADING_MANAGER_DASHBOARD_REFRESH_SERVICE_UNIT") or "trading-storage-dashboard-read-model-refresh.service"
    drain_enabled = _env_bool(values, "TRADING_MANAGER_DRAIN_READY_STAGES", True)
    cpu_count = os.cpu_count() or 1
    load_1m = float(host.get("load_average_1m") or 0.0)
    memory_available_mb = int(host.get("memory_available_mb") or 0)
    load_headroom = max(0.0, (cpu_count * DEFAULT_PROVIDER_STAGE_LOAD_TARGET_PER_CPU) - load_1m)
    load_worker_capacity = max(1, int(load_headroom // 0.5) or 1)
    memory_headroom = max(0, memory_available_mb - DEFAULT_PROVIDER_STAGE_RESERVED_MEMORY_MB)
    memory_worker_capacity = max(1, memory_headroom // DEFAULT_PROVIDER_STAGE_WORKER_MEMORY_MB)
    selected_workers = max(1, min(max_workers, next_limit, load_worker_capacity, memory_worker_capacity))
    return {
        "mode": "dynamic",
        "selected_worker_count": selected_workers,
        "max_worker_count": max_workers,
        "next_request_limit": next_limit,
        "scheduler_interval_seconds": interval_seconds,
        "scheduler_interval_role": "idle_backstop" if drain_enabled else "primary_tick",
        "drain_ready_stages": drain_enabled,
        "drain_max_steps": drain_max_steps,
        "drain_max_seconds": drain_max_seconds,
        "event_refresh_enabled": True,
        "event_refresh_service_unit": refresh_service_unit,
        "load_target_per_cpu": DEFAULT_PROVIDER_STAGE_LOAD_TARGET_PER_CPU,
        "load_1m": load_1m,
        "cpu_count": cpu_count,
        "memory_available_mb": memory_available_mb,
        "worker_memory_mb": DEFAULT_PROVIDER_STAGE_WORKER_MEMORY_MB,
        "reserved_memory_mb": DEFAULT_PROVIDER_STAGE_RESERVED_MEMORY_MB,
        "status": "active" if selected_workers > 1 else "single_worker",
        "reason": "dynamic provider worker count selected from current load and available memory",
    }


def _storage_refresh_cadence_seconds() -> int:
    values = _read_env_file(DEFAULT_STORAGE_REFRESH_ENV_PATH)
    if os.environ.get("TRADING_STORAGE_REFRESH_CADENCE_SECONDS"):
        values = values | {"TRADING_STORAGE_REFRESH_CADENCE_SECONDS": os.environ["TRADING_STORAGE_REFRESH_CADENCE_SECONDS"]}
    return _env_int(values, "TRADING_STORAGE_REFRESH_CADENCE_SECONDS", DEFAULT_REFRESH_CADENCE_SECONDS)


def _host_resources(storage_root: Path) -> dict[str, Any]:
    storage_root.mkdir(parents=True, exist_ok=True)
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


def _service_by_unit(services: list[Mapping[str, Any]], unit: str) -> Mapping[str, Any]:
    return next((service for service in services if service.get("unit") == unit), {})


def _source_connection_statuses(
    *,
    services: list[Mapping[str, Any]],
    storage_root: Path,
    now_epoch: float,
) -> list[dict[str, Any]]:
    connections = _provider_api_statuses()
    te_root = storage_root / "01_source_data/monthly_backfill/trading_economics_calendar_web"
    event_file = _source_output_status(
        _latest_matching_file(te_root, "**/saved/trading_economics_calendar_event.csv"),
        label="Trading Economics Calendar Source",
        kind="trading_economics_calendar_storage_snapshot",
        now_epoch=now_epoch,
        freshness_class="event_driven",
        freshness_note="Canonical TE macro source rows update when the bounded recent/future refresh appends storage data.",
    )
    if event_file["status"] == "available":
        status = "available"
    else:
        status = "missing_snapshot"
    connections.append(
        {
            "name": "Trading Economics Calendar Source",
            "kind": "economic_calendar_storage_source",
            "status": status,
            "healthy": event_file["status"] == "available",
            "latest_updated_at_utc": event_file["latest_updated_at_utc"],
            "age_seconds": event_file["age_seconds"],
        }
    )
    return connections


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


def _source_output_status(
    path: Path | None,
    *,
    label: str,
    kind: str,
    now_epoch: float,
    freshness_class: str,
    freshness_note: str,
) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "label": label,
            "kind": kind,
            "status": "missing",
            "exists": False,
            "age_seconds": None,
            "latest_updated_at_utc": None,
            "freshness_class": freshness_class,
            "freshness_note": freshness_note,
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
                "freshness_class": freshness_class,
                "freshness_note": freshness_note,
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
        "freshness_class": freshness_class,
        "freshness_note": freshness_note,
    }


def _latest_matching_file(root: Path, pattern: str) -> Path | None:
    try:
        matches = [path for path in root.glob(pattern) if path.is_file()]
    except OSError:
        return None
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _active_workflow_state_path(runtime_root: Path) -> Path | None:
    scheduler_state_path = runtime_root / "historical_scheduler_state.json"
    try:
        scheduler_state = json.loads(scheduler_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        scheduler_state = {}
    if isinstance(scheduler_state, Mapping):
        active_month = scheduler_state.get("start_month") or scheduler_state.get("current_month")
        if isinstance(active_month, str) and active_month:
            active_path = runtime_root / f"model_training_workflow_state_{active_month}.json"
            if active_path.exists():
                return active_path
            return active_path
    return _latest_matching_file(runtime_root, "model_training_workflow_state_????-??.json")


def _manager_storage_root_from(storage_root: Path) -> Path:
    override = os.environ.get("TRADING_MANAGER_STORAGE_ROOT")
    return Path(override) if override else Path(storage_root) / "02_control_plane"


def _dashboard_source_outputs(*, storage_root: Path, manager_storage_root: Path, now_epoch: float) -> list[dict[str, Any]]:
    runtime_root = manager_storage_root / "runtime"
    heartbeat_note = "Expected to update on scheduler heartbeat; old timestamps can indicate daemon trouble."
    event_note = "Event-driven artifact; timestamp changes only when the scheduler makes a decision or stage progress occurs."
    dashboard_note = "Storage-hosted dashboard read model consumed by the website API and WebSocket stream."
    execution_note = "Execution-owned runtime artifact consumed through storage-hosted read models; no broker mutation is performed by the dashboard."
    source_note = "Source-data artifact produced by a bounded provider/data refresh path and consumed only as read-only freshness evidence here."
    # Keep this inventory synchronized with website/read-model slices that consume
    # original source outputs. The dashboard JSON is only a sanitized cache; these
    # rows preserve owner-facing freshness for the canonical source artifacts.
    output_specs: list[tuple[str, str, Path | None, str, str]] = [
        ("Historical Scheduler State", "manager_scheduler_state", runtime_root / "historical_scheduler_state.json", "heartbeat", heartbeat_note),
        ("Scheduler Decision Log", "manager_scheduler_decision_log", runtime_root / "historical_scheduler_decisions.jsonl", "event_driven", event_note),
        ("Active Workflow State", "manager_workflow_state", _active_workflow_state_path(runtime_root), "event_driven", event_note),
        (
            "Latest Stage Coverage Output",
            "manager_stage_coverage",
            _latest_matching_file(runtime_root / "stage_coverage", "*.json"),
            "event_driven",
            event_note,
        ),
        (
            "Latest Stage Run Output",
            "manager_stage_run_dashboard",
            _latest_matching_file(runtime_root / "stage_run_dashboard", "*.json"),
            "event_driven",
            event_note,
        ),
        (
            "Execution Runtime Status",
            "execution_runtime_status",
            storage_root / "04_execution_artifacts/runtime/realtime_trading_runtime/runtime_status.json",
            "event_driven",
            execution_note,
        ),
        (
            "Latest Realtime Monitor Receipt",
            "execution_realtime_monitor_receipt",
            _latest_matching_file(storage_root / "04_execution_artifacts/runtime/realtime_monitor", "**/loop_receipt.json"),
            "heartbeat",
            execution_note,
        ),
        (
            "Latest Realtime Monitor Cycle",
            "execution_realtime_monitor_cycle",
            _latest_matching_file(storage_root / "04_execution_artifacts/runtime/realtime_monitor", "**/cycle_*.json"),
            "heartbeat",
            execution_note,
        ),
        (
            "Trading Economics Canonical Source Receipt",
            "trading_economics_calendar_source_receipt",
            _latest_matching_file(storage_root / "01_source_data/monthly_backfill/trading_economics_calendar_web", "**/completion_receipt.json"),
            "event_driven",
            source_note,
        ),
        (
            "Trading Economics Canonical Source Events",
            "trading_economics_calendar_source_events",
            _latest_matching_file(storage_root / "01_source_data/monthly_backfill/trading_economics_calendar_web", "**/saved/trading_economics_calendar_event.csv"),
            "event_driven",
            source_note,
        ),
        (
            "Dashboard Read Model Index",
            "storage_dashboard_read_model_index",
            storage_root / "06_dashboard_cache/index/dashboard_read_model_index.jsonl",
            "heartbeat",
            dashboard_note,
        ),
        (
            "Status Read Model",
            "storage_dashboard_current_status_latest",
            storage_root / "06_dashboard_cache/read_models/current_system_status_summary/latest.json",
            "heartbeat",
            dashboard_note,
        ),
        (
            "Historical Task Progress Read Model",
            "storage_dashboard_historical_task_progress_latest",
            storage_root / "06_dashboard_cache/read_models/historical_task_progress_summary/latest.json",
            "heartbeat",
            dashboard_note,
        ),
        (
            "Realtime Signal Summary Read Model",
            "storage_dashboard_realtime_signal_latest",
            storage_root / "06_dashboard_cache/read_models/realtime_signal_summary/latest.json",
            "heartbeat",
            dashboard_note,
        ),
        (
            "Temporal Explorer Read Model",
            "storage_dashboard_temporal_explorer_latest",
            storage_root / "06_dashboard_cache/read_models/temporal_explorer_summary/latest.json",
            "heartbeat",
            dashboard_note,
        ),
        (
            "Execution Runtime Read Model",
            "storage_dashboard_execution_runtime_latest",
            storage_root / "06_dashboard_cache/read_models/execution_realtime_trading_runtime_status/latest.json",
            "heartbeat",
            dashboard_note,
        ),
    ]
    outputs: list[dict[str, Any]] = []
    for label, kind, path, freshness_class, freshness_note in output_specs:
        if path is None:
            outputs.append(
                {
                    "label": label,
                    "kind": kind,
                    "status": "missing",
                    "exists": False,
                    "age_seconds": None,
                    "latest_updated_at_utc": None,
                    "freshness_class": freshness_class,
                    "freshness_note": freshness_note,
                }
            )
            continue
        outputs.append(
            _source_output_status(
                path,
                label=label,
                kind=kind,
                now_epoch=now_epoch,
                freshness_class=freshness_class,
                freshness_note=freshness_note,
            )
        )
    return outputs


def build_current_system_status_summary(*, storage_root: Path, generated_at_utc: str | None = None) -> dict[str, Any]:
    generated_at_utc = generated_at_utc or now_utc()
    now_epoch = time.time()
    host = _host_resources(storage_root)
    parallelism = _historical_scheduler_parallelism(host)
    manager_storage_root = _manager_storage_root_from(storage_root)
    runtime_values = _read_env_file(DEFAULT_TRADING_MANAGER_ROOT / "deploy/systemd/trading-manager-historical-scheduler.env") | _read_env_file(DEFAULT_SCHEDULER_ENV_PATH)
    runtime_throughput = _historical_scheduler_runtime_throughput(values=runtime_values, manager_storage_root=manager_storage_root)
    services = [_systemd_unit(unit) for unit in _trading_systemd_unit_names()]
    source_outputs = _dashboard_source_outputs(storage_root=storage_root, manager_storage_root=manager_storage_root, now_epoch=now_epoch)
    source_outputs = _mark_parked_execution_outputs(source_outputs, services=services)
    scheduler_active = _historical_scheduler_is_active(services)
    if not scheduler_active:
        source_outputs = _mark_source_outputs_not_started(source_outputs)
    else:
        source_outputs = _mark_missing_event_outputs_waiting(source_outputs)
    source_connections = _source_connection_statuses(services=services, storage_root=storage_root, now_epoch=now_epoch)
    unhealthy_services = [service["unit"] for service in services if not service["healthy"]]
    missing_outputs = [
        output["label"]
        for output in source_outputs
        if output["status"] == "missing"
    ]
    severity = "info" if not unhealthy_services and not missing_outputs else "medium"
    status = "healthy" if severity == "info" else "degraded"
    summary = (
        "Infrastructure status is healthy; refresh timer, provider API configuration, observed services, and dashboard source outputs are available."
        if status == "healthy" and scheduler_active
        else "Infrastructure is healthy and historical training is stopped; runtime source outputs will appear after the scheduler starts."
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
            "parallelism": parallelism,
            "runtime_throughput": runtime_throughput,
            "api": {
                "http_latest_route": "/api/read-models/<contract_type>/latest",
                "websocket_latest_route": "/ws/read-models/<contract_type>/latest",
                "status": "configured",
            },
            "apis": source_connections,
            "source_connections": source_connections,
            "services": services,
            "source_outputs": source_outputs,
            "refresh": {
                "timer_unit": "trading-storage-dashboard-read-model-refresh.timer",
                "cadence_seconds": _storage_refresh_cadence_seconds(),
                "status": next(
                    (
                        service["active_state"]
                        for service in services
                        if service["unit"] == "trading-storage-dashboard-read-model-refresh.timer"
                    ),
                    "unknown",
                ),
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
            {"ref_type": "scheduler_parallelism", "selected_worker_count": parallelism["selected_worker_count"]},
            {"ref_type": "scheduler_runtime_throughput", "executed_decision_count": runtime_throughput["executed_decision_count"]},
            {"ref_type": "dashboard_source_outputs", "count": len(source_outputs)},
        ],
        "lineage_refs": [
            {"contract_type": "systemd_unit_status", "included": True},
            {"contract_type": "host_resource_snapshot", "included": True},
            {"contract_type": "scheduler_parallelism_status", "included": True},
            {"contract_type": "scheduler_runtime_throughput", "included": True},
            {"contract_type": "dashboard_source_output_files", "included": True},
        ],
        "freshness": {"class": "infrastructure_status_snapshot", "status": "fresh", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
        "schema_ref": CURRENT_SYSTEM_STATUS_SCHEMA_REF,
    }


def refresh_current_system_status_read_model(*, storage_root: Path = Path("storage")) -> dict[str, Any]:
    storage_root.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("--refresh", action="store_true", help="Materialize the summary into storage/06_dashboard_cache instead of printing only.")
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
    "_storage_refresh_cadence_seconds",
]
