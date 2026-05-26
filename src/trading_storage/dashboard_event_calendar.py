"""Event calendar dashboard read-model producer.

The producer reads already-materialized event overview rows from SQL and
storage-hosted TE refresh evidence. It does not call providers, schedule work,
activate models, submit broker orders, or mutate account state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TextIO

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

EVENT_CALENDAR_SUMMARY_CONTRACT = "event_calendar_summary"
EVENT_CALENDAR_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{EVENT_CALENDAR_SUMMARY_CONTRACT}.schema.json"
DEFAULT_STORAGE_ROOT = Path(os.environ.get("TRADING_STORAGE_ROOT", "/root/projects/trading-storage")) / "storage"
DEFAULT_SQL_SCHEMA = "trading_data"
DEFAULT_SQL_TABLE = "source_10_event_risk_governor"
TE_SOURCE_NAME = "07_feed_trading_economics_calendar_web"
TE_SOURCE_ROOT = Path("01_source_data/monthly_backfill/trading_economics_calendar_web")
DEFAULT_LOOKBACK_DAYS = 14
DEFAULT_LOOKAHEAD_DAYS = 45


def _parse_utc(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mtime_utc(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))


def _latest_matching_file(root: Path, pattern: str) -> Path | None:
    try:
        matches = [path for path in root.glob(pattern) if path.is_file()]
    except OSError:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def _unit_status(unit: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,Result,UnitFileState"],
        text=True,
        capture_output=True,
        check=False,
        timeout=2,
    )
    values: dict[str, str] = {}
    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    active_state = values.get("ActiveState") or "unknown"
    result = values.get("Result") or ""
    return {
        "unit": unit,
        "active_state": active_state,
        "substate": values.get("SubState") or "unknown",
        "enabled_state": values.get("UnitFileState") or "unknown",
        "result": result,
        "healthy": active_state == "active" or (active_state == "inactive" and result in {"success", ""}),
    }


def _load_secret_values(alias: str) -> Mapping[str, Any]:
    secret_root = Path(os.environ.get("TRADING_SECRET_ROOT", "/root/secrets"))
    direct = secret_root / f"{alias}.json"
    if direct.exists():
        return json.loads(direct.read_text(encoding="utf-8"))
    registry_path = secret_root / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    target = registry.get(alias)
    if isinstance(target, str):
        path = Path(target)
        if not path.is_absolute():
            path = secret_root / target
        return json.loads(path.read_text(encoding="utf-8"))
    if isinstance(target, Mapping):
        return target
    raise RuntimeError(f"missing secret alias {alias!r}")


def _postgres_dsn() -> str:
    direct = os.environ.get("TRADING_DATA_POSTGRES_DSN") or os.environ.get("TRADING_STORAGE_POSTGRES_DSN")
    if direct:
        return direct
    values = _load_secret_values(os.environ.get("TRADING_STORAGE_POSTGRES_SECRET_ALIAS", "trading_storage_postgres"))
    dsn = str(values.get("dsn") or "").strip()
    if dsn:
        return dsn
    host = values.get("host")
    database = values.get("database") or values.get("dbname")
    user = values.get("user") or values.get("username")
    password = values.get("password")
    port = values.get("port") or 5432
    if not (host and database and user and password):
        raise RuntimeError("PostgreSQL calendar summary requires dsn or host/database/user/password")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _fetch_event_rows_from_sql(
    *,
    now: datetime,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
    schema: str = DEFAULT_SQL_SCHEMA,
    table: str = DEFAULT_SQL_TABLE,
) -> list[dict[str, Any]]:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - host dependency
        raise RuntimeError("event calendar summary requires psycopg") from exc
    start = now - timedelta(days=lookback_days)
    end = now + timedelta(days=lookahead_days)
    query = f"""
        SELECT event_id, event_time, available_time, event_category_type, scope_type, symbol, title,
               source_name, source_priority, coverage_reason, reference_type, reference, source_artifact_path, summary
        FROM "{schema}"."{table}"
        WHERE event_time >= %s AND event_time < %s
          AND (
            event_category_type IN ('macro_data', 'earnings_guidance')
            OR source_name = %s
          )
        ORDER BY event_time ASC, event_id ASC
    """
    with psycopg.connect(_postgres_dsn(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (start, end, TE_SOURCE_NAME))
            return [dict(row) for row in cursor.fetchall()]


def _event_item(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    event_time = _parse_utc(str(row.get("event_time") or "")) or now
    source_name = str(row.get("source_name") or "")
    source_priority = str(row.get("source_priority") or "unknown")
    category = str(row.get("event_category_type") or "event")
    event_phase = "scheduled" if event_time >= now and source_priority == "approved_calendar" else "released" if event_time < now else "upcoming"
    return {
        "event_id": str(row.get("event_id") or ""),
        "event_time": _iso_utc(event_time),
        "available_time": str(row.get("available_time") or ""),
        "title": str(row.get("title") or "Untitled event"),
        "event_category_type": category,
        "scope_type": str(row.get("scope_type") or "macro"),
        "symbol": row.get("symbol"),
        "source_name": source_name,
        "source_priority": source_priority,
        "event_phase": event_phase,
        "reference_type": str(row.get("reference_type") or ""),
        "has_source_artifact_path": bool(row.get("source_artifact_path")),
        "summary": str(row.get("summary") or ""),
    }


def _family_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    category_counts = Counter(str(row.get("event_category_type") or "unknown") for row in rows)
    source_counts = Counter(str(row.get("source_name") or "unknown") for row in rows)
    te_count = source_counts.get(TE_SOURCE_NAME, 0)
    earnings_count = category_counts.get("earnings_guidance", 0)
    return [
        {
            "family_id": "macro_scheduled_releases",
            "label": "Macro scheduled releases",
            "status": "active" if te_count else "no_rows_in_window",
            "event_count": te_count,
            "primary_source": "Trading Economics visible calendar",
        },
        {
            "family_id": "earnings_scheduled_shells",
            "label": "Earnings scheduled shells",
            "status": "active" if earnings_count else "ready_no_rows_in_window",
            "event_count": earnings_count,
            "primary_source": "Nasdaq earnings calendar shell artifacts",
        },
        {
            "family_id": "exchange_holidays_early_closes",
            "label": "Exchange holidays and early closes",
            "status": "not_connected",
            "event_count": 0,
            "primary_source": "Official exchange calendars",
        },
        {
            "family_id": "option_expiry_windows",
            "label": "Option expiry windows",
            "status": "not_connected",
            "event_count": 0,
            "primary_source": "OCC/Cboe calendars and deterministic rules",
        },
        {
            "family_id": "index_rebalance_windows",
            "label": "Index rebalance windows",
            "status": "not_connected",
            "event_count": 0,
            "primary_source": "Index provider announcements/calendars",
        },
    ]


def build_event_calendar_summary(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    rows: Sequence[Mapping[str, Any]] | None = None,
    generated_at_utc: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
) -> dict[str, Any]:
    generated_at_utc = generated_at_utc or now_utc()
    now = _parse_utc(generated_at_utc) or datetime.now(UTC)
    storage_root = Path(storage_root)
    rows = list(rows) if rows is not None else _fetch_event_rows_from_sql(now=now, lookback_days=lookback_days, lookahead_days=lookahead_days)
    items = [_event_item(row, now=now) for row in rows]
    upcoming = [item for item in items if (_parse_utc(item["event_time"]) or now) >= now]
    recent = [item for item in items if (_parse_utc(item["event_time"]) or now) < now]
    by_category = Counter(item["event_category_type"] for item in items)
    by_source = Counter(item["source_name"] for item in items)
    te_root = storage_root / TE_SOURCE_ROOT
    latest_receipt = _latest_matching_file(te_root, "**/completion_receipt.json")
    latest_event_file = _latest_matching_file(te_root, "**/saved/trading_economics_calendar_event.csv")
    timer_status = _unit_status("trading-data-te-calendar-refresh.timer")
    service_status = _unit_status("trading-data-te-calendar-refresh.service")
    connected_families = sum(1 for family in _family_rows(rows) if family["status"] in {"active", "ready_no_rows_in_window"})
    status = "ready" if rows else "empty"
    summary = (
        f"Calendar has {len(upcoming)} upcoming and {len(recent)} recent events across {connected_families} connected calendar families."
        if rows
        else "Calendar read model is available, but no event rows matched the current window."
    )
    return {
        "contract_type": EVENT_CALENDAR_SUMMARY_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": status,
        "severity": "info" if status == "ready" else "medium",
        "summary": summary,
        "chart_payload": {
            "window": {
                "lookback_days": lookback_days,
                "lookahead_days": lookahead_days,
                "start_utc": _iso_utc(now - timedelta(days=lookback_days)),
                "end_utc": _iso_utc(now + timedelta(days=lookahead_days)),
            },
            "counts": {
                "total_events": len(items),
                "upcoming_events": len(upcoming),
                "recent_events": len(recent),
                "events_with_source_artifact_path": sum(1 for item in items if item["has_source_artifact_path"]),
                "by_category": dict(sorted(by_category.items())),
                "by_source": dict(sorted(by_source.items())),
            },
            "refresh": {
                "timer": timer_status,
                "service": service_status,
                "latest_te_receipt_updated_at_utc": _mtime_utc(latest_receipt),
                "latest_te_event_file_updated_at_utc": _mtime_utc(latest_event_file),
            },
            "families": _family_rows(rows),
            "upcoming_events": upcoming[:80],
            "recent_events": list(reversed(recent))[:40],
        },
        "profile_refs": [
            {"registry_ref": "EVENT_CALENDAR_SUMMARY", "field": "contract_type"},
            {"registry_ref": "TRADING_ECONOMICS_APPEND_ONLY_RETENTION_POLICY", "field": "source_artifact_path"},
        ],
        "issue_refs": [],
        "diagnostic_refs": [
            {"ref_type": "calendar_sql_rows", "count": len(items)},
            {"ref_type": "calendar_family_status", "connected_family_count": connected_families},
        ],
        "lineage_refs": [
            {"contract_type": "source_10_event_risk_governor", "included": True},
            {"contract_type": "trading_economics_monthly_backfill_source_root", "path": str(te_root)},
        ],
        "freshness": {"class": "calendar_event_snapshot", "status": "fresh", "stale_after_seconds": 3600},
        "schema_ref": EVENT_CALENDAR_SCHEMA_REF,
    }


def refresh_event_calendar_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    storage_root = Path(storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    payload = build_event_calendar_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=EVENT_CALENDAR_SUMMARY_CONTRACT)
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": EVENT_CALENDAR_SUMMARY_CONTRACT,
        "materialized": materialized.index_row,
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


def write_event_calendar_summary(payload: Mapping[str, Any], *, output: TextIO) -> None:
    json.dump(dict(payload), output, indent=2, sort_keys=True)
    output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or refresh event_calendar_summary from accepted event-calendar SQL rows.")
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--refresh", action="store_true", help="Materialize the summary under storage/06_dashboard_cache.")
    args = parser.parse_args(argv)
    if args.refresh:
        json.dump(refresh_event_calendar_summary_read_model(storage_root=args.storage_root), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    write_event_calendar_summary(build_event_calendar_summary(storage_root=args.storage_root), output=sys.stdout)
    return 0


__all__ = [
    "EVENT_CALENDAR_SUMMARY_CONTRACT",
    "build_event_calendar_summary",
    "refresh_event_calendar_summary_read_model",
    "write_event_calendar_summary",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
