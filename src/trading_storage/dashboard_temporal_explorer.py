"""Temporal Explorer dashboard read-model producer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO
from zoneinfo import ZoneInfo

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

TEMPORAL_EXPLORER_SUMMARY_CONTRACT = "temporal_explorer_summary"
TEMPORAL_EXPLORER_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{TEMPORAL_EXPLORER_SUMMARY_CONTRACT}.schema.json"
DEFAULT_STORAGE_ROOT = Path(os.environ.get("TRADING_STORAGE_ROOT", "/root/projects/trading-storage")) / "storage"
DEFAULT_SQL_SCHEMA = "trading_data"
DEFAULT_FRAME = "1D"
DEFAULT_CENTER_LOOKBACK_DAYS = 14
DEFAULT_CENTER_LOOKAHEAD_DAYS = 45
SUPPORTED_FRAMES = ("1D", "1W")
DEFAULT_CHART_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")
SOURCE_BAR_TABLE = "model_01_market_regime_data_acquisition"
DEFAULT_REPLAY_START_MONTH = "2021-01"
DEFAULT_REPLAY_END_MONTH = "2026-01"
OPERATOR_TIMEZONE = ZoneInfo("America/New_York")

SUBSTRATE_TABLES = (
    "calendar_day",
    "calendar_market_session",
    "calendar_scheduled_event",
    "calendar_event_result",
    "calendar_news_event_index",
    "chart_ohlcv_cache",
)


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
        raise RuntimeError("PostgreSQL Temporal Explorer summary requires dsn or host/database/user/password")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _frame_delta(frame: str) -> timedelta:
    if frame == "30m":
        return timedelta(minutes=30)
    if frame == "1h":
        return timedelta(hours=1)
    if frame == "1W":
        return timedelta(days=7)
    return timedelta(days=1)


def _chart_timeframe(frame: str) -> str:
    return {"30m": "10min", "1h": "30min", "1D": "1D", "1W": "1W"}.get(frame, "1D")


def _is_month_key(value: str) -> bool:
    if len(value) != 7 or value[4] != "-":
        return False
    year, month = value.split("-", 1)
    return year.isdigit() and month.isdigit() and 1 <= int(month) <= 12


def _month_start_utc(month: str) -> datetime:
    if not _is_month_key(month):
        month = DEFAULT_REPLAY_START_MONTH
    return datetime(int(month[:4]), int(month[5:]), 1, tzinfo=OPERATOR_TIMEZONE).astimezone(UTC)


def _add_months(month: str, count: int) -> str:
    base = _month_start_utc(month)
    index = base.year * 12 + base.month - 1 + count
    year, month_number = divmod(index, 12)
    return f"{year:04d}-{month_number + 1:02d}"


def _window_from_months(start_month: str, end_month: str) -> tuple[datetime, datetime]:
    start = _month_start_utc(start_month)
    end = _month_start_utc(_add_months(end_month, 1))
    if end <= start:
        return _window_from_months(DEFAULT_REPLAY_START_MONTH, DEFAULT_REPLAY_END_MONTH)
    return start, end


def _replay_window_from_progress_summary(storage_root: Path) -> tuple[str, str] | None:
    summary = _read_json(storage_root / "06_dashboard_cache/read_models/historical_task_progress_summary.json")
    task_timeline = ((summary or {}).get("chart_payload") or {}).get("task_timeline")
    if not isinstance(task_timeline, Sequence) or isinstance(task_timeline, (str, bytes)):
        return None
    for task in task_timeline:
        if not isinstance(task, Mapping):
            continue
        detail = task.get("detail")
        replay_window = detail.get("replay_window") if isinstance(detail, Mapping) else None
        if not isinstance(replay_window, Mapping):
            continue
        if replay_window.get("unit_kind") != "model_group_replay_window":
            continue
        start_month = str(replay_window.get("start_month") or "")
        end_month = str(replay_window.get("end_month") or "")
        if _is_month_key(start_month) and _is_month_key(end_month):
            return start_month, end_month
    return None


def _source_bar_bucket_seconds(timeframe: str) -> int | None:
    if timeframe == "10min":
        return 10 * 60
    if timeframe == "30min":
        return 30 * 60
    return None


def _source_bar_bucket_expression(timeframe: str) -> str:
    if timeframe == "1D":
        return "date_trunc('day', timestamp)"
    if timeframe == "1W":
        return "date_trunc('week', timestamp)"
    seconds = _source_bar_bucket_seconds(timeframe) or 60 * 60
    return f"to_timestamp(floor(extract(epoch from timestamp) / {seconds}) * {seconds})"


def _source_bar_bucket_end_expression(timeframe: str) -> str:
    if timeframe == "1D":
        return "bucket_start + interval '1 day'"
    if timeframe == "1W":
        return "bucket_start + interval '7 days'"
    seconds = _source_bar_bucket_seconds(timeframe) or 60 * 60
    return f"bucket_start + interval '{seconds} seconds'"


def _latest_source_bar_center(*, symbol: str = "SPY", schema: str = DEFAULT_SQL_SCHEMA) -> datetime | None:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with psycopg.connect(_postgres_dsn(), row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM information_schema.tables
                      WHERE table_schema = %s AND table_name = %s
                    ) AS exists
                    """,
                    (schema, SOURCE_BAR_TABLE),
                )
                if not bool(cursor.fetchone()["exists"]):
                    return None
                cursor.execute(
                    f"""
                    SELECT max(timestamp) AS center_time
                    FROM "{schema}"."{SOURCE_BAR_TABLE}"
                    WHERE symbol = %s AND timeframe = '1Min'
                    """,
                    (symbol,),
                )
                value = cursor.fetchone()["center_time"]
    except Exception:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return _parse_utc(str(value or ""))


def _fetch_source_chart_bars(
    cursor: Any,
    schema: str,
    *,
    symbols: Sequence[str],
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = %s AND table_name = %s
        ) AS exists
        """,
        (schema, SOURCE_BAR_TABLE),
    )
    if not bool(cursor.fetchone()["exists"]):
        return []
    bucket_expression = _source_bar_bucket_expression(timeframe)
    bucket_end_expression = _source_bar_bucket_end_expression(timeframe)
    cursor.execute(
        f"""
        WITH source AS (
          SELECT
            symbol,
            {bucket_expression} AS bucket_start,
            timestamp,
            bar_open,
            bar_high,
            bar_low,
            bar_close,
            bar_volume,
            bar_vwap
          FROM "{schema}"."{SOURCE_BAR_TABLE}"
          WHERE symbol = ANY(%s)
            AND timeframe = '1Min'
            AND timestamp >= %s
            AND timestamp < %s
        ),
        grouped AS (
          SELECT
            symbol,
            %s AS timeframe,
            bucket_start,
            {bucket_end_expression} AS bucket_end,
            (array_agg(bar_open ORDER BY timestamp ASC))[1] AS open,
            max(bar_high) AS high,
            min(bar_low) AS low,
            (array_agg(bar_close ORDER BY timestamp DESC))[1] AS close,
            sum(coalesce(bar_volume, 0)) AS volume,
            CASE
              WHEN sum(coalesce(bar_volume, 0)) > 0
              THEN sum(coalesce(bar_vwap, bar_close) * coalesce(bar_volume, 0)) / sum(coalesce(bar_volume, 0))
              ELSE avg(coalesce(bar_vwap, bar_close))
            END AS vwap,
            count(*) AS bar_count
          FROM source
          GROUP BY symbol, bucket_start
        )
        SELECT
          symbol,
          timeframe,
          bucket_start,
          bucket_end,
          open,
          high,
          low,
          close,
          volume,
          vwap,
          bar_count,
          jsonb_build_object('source_table', %s::text, 'source_timeframe', '1Min', 'derived_for_display', true) AS quality_flags_json,
          'source_bar_sql' AS chart_source
        FROM grouped
        WHERE bucket_start >= %s AND bucket_start < %s
        ORDER BY symbol ASC, bucket_start ASC
        LIMIT 10000
        """,
        (list(symbols), start, end, timeframe, SOURCE_BAR_TABLE, start, end),
    )
    return [dict(row) for row in cursor.fetchall()]


def _table_statuses(*, schema: str = DEFAULT_SQL_SCHEMA) -> dict[str, dict[str, Any]]:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except ImportError:
        return {table: {"status": "driver_missing", "row_count": 0} for table in SUBSTRATE_TABLES}
    statuses: dict[str, dict[str, Any]] = {}
    try:
        with psycopg.connect(_postgres_dsn(), row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                for table in SUBSTRATE_TABLES:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM information_schema.tables
                          WHERE table_schema = %s AND table_name = %s
                        ) AS exists
                        """,
                        (schema, table),
                    )
                    exists = bool(cursor.fetchone()["exists"])
                    row_count = 0
                    if exists:
                        cursor.execute(f'SELECT count(*) AS row_count FROM "{schema}"."{table}"')
                        row_count = int(cursor.fetchone()["row_count"])
                    statuses[table] = {
                        "status": "populated" if row_count else "empty" if exists else "missing",
                        "row_count": row_count,
                    }
    except Exception as exc:  # noqa: BLE001 - dashboard read models degrade instead of failing the page
        return {table: {"status": "unavailable", "row_count": 0, "reason": exc.__class__.__name__} for table in SUBSTRATE_TABLES}
    return statuses


def _fetch_sql_rows(
    *,
    start_time: datetime,
    end_time: datetime,
    frame: str,
    schema: str = DEFAULT_SQL_SCHEMA,
) -> dict[str, list[dict[str, Any]]]:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except ImportError:
        return {"sessions": [], "scheduled_events": [], "event_results": [], "news_events": [], "chart_bars": []}
    rows: dict[str, list[dict[str, Any]]] = {}
    try:
        with psycopg.connect(_postgres_dsn(), row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                rows["sessions"] = _fetch_optional(
                    cursor,
                    schema,
                    "calendar_market_session",
                    """
                    SELECT venue, calendar_date, is_trading_day, session_type, open_time, close_time, holiday_name, source_priority
                    FROM {table}
                    WHERE calendar_date >= %s::date AND calendar_date < %s::date
                    ORDER BY calendar_date ASC, venue ASC
                    """,
                    (start_time.date(), end_time.date()),
                )
                rows["scheduled_events"] = _fetch_optional(
                    cursor,
                    schema,
                    "calendar_scheduled_event",
                    """
                    SELECT event_id, event_time, event_date, event_type, event_scope, symbol, country, source_priority, scheduled_known_at, raw_artifact_ref, metadata_json
                    FROM {table}
                    WHERE event_date >= %s::date AND event_date < %s::date
                    ORDER BY event_date ASC, event_time ASC NULLS LAST, event_id ASC
                    LIMIT 500
                    """,
                    (start_time.date(), end_time.date()),
                )
                rows["event_results"] = _fetch_optional(
                    cursor,
                    schema,
                    "calendar_event_result",
                    """
                    SELECT event_id, released_at, available_time, retrieved_at
                    FROM {table}
                    WHERE available_time >= %s AND available_time < %s
                    ORDER BY available_time ASC, event_id ASC
                    LIMIT 500
                    """,
                    (start_time, end_time),
                )
                rows["news_events"] = _fetch_optional(
                    cursor,
                    schema,
                    "calendar_news_event_index",
                    """
                    SELECT news_event_id, event_date, first_seen_at, source, headline, symbol, event_family_candidate, dedup_status, raw_artifact_ref, interpreted_event_ref
                    FROM {table}
                    WHERE first_seen_at >= %s AND first_seen_at < %s
                    ORDER BY first_seen_at ASC, news_event_id ASC
                    LIMIT 500
                    """,
                    (start_time, end_time),
                )
                chart_bars: list[dict[str, Any]] = []
                for chart_timeframe in dict.fromkeys(_chart_timeframe(value) for value in SUPPORTED_FRAMES):
                    cached_bars = _fetch_optional(
                        cursor,
                        schema,
                        "chart_ohlcv_cache",
                        """
                        SELECT symbol, timeframe, bucket_start, bucket_end, open, high, low, close, volume, vwap, bar_count, quality_flags_json
                        FROM {table}
                        WHERE symbol = ANY(%s) AND timeframe = %s AND bucket_start >= %s AND bucket_start < %s
                        ORDER BY symbol ASC, bucket_start ASC
                        LIMIT 10000
                        """,
                        (list(DEFAULT_CHART_SYMBOLS), chart_timeframe, start_time, end_time),
                    )
                    cached_symbols = {str(row.get("symbol") or "").upper() for row in cached_bars}
                    if not cached_bars or set(DEFAULT_CHART_SYMBOLS) - cached_symbols:
                        cached_bars = _fetch_source_chart_bars(
                            cursor,
                            schema,
                            symbols=DEFAULT_CHART_SYMBOLS,
                            timeframe=chart_timeframe,
                            start=start_time,
                            end=end_time,
                        )
                    chart_bars.extend(cached_bars)
                rows["chart_bars"] = chart_bars
    except Exception:
        return {"sessions": [], "scheduled_events": [], "event_results": [], "news_events": [], "chart_bars": []}
    return rows


def _fetch_optional(cursor: Any, schema: str, table_name: str, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = %s AND table_name = %s
        ) AS exists
        """,
        (schema, table_name),
    )
    if not bool(cursor.fetchone()["exists"]):
        return []
    cursor.execute(query.format(table=f'"{schema}"."{table_name}"'), params)
    return [dict(row) for row in cursor.fetchall()]


def _event_time(item: Mapping[str, Any]) -> datetime | None:
    for field in ("event_time", "available_time", "first_seen_at", "released_at"):
        parsed = _parse_utc(str(item.get(field) or ""))
        if parsed:
            return parsed
    event_date = item.get("event_date")
    if event_date:
        return datetime.fromisoformat(str(event_date)).replace(tzinfo=UTC)
    return None


def _row_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None:
        return ""
    return str(value).strip()


def _row_metadata(row: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = row.get("metadata_json")
    if isinstance(metadata, Mapping):
        return metadata
    if isinstance(metadata, str) and metadata.strip():
        try:
            decoded = json.loads(metadata)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, Mapping) else {}
    return {}


def _metadata_text(row: Mapping[str, Any], field: str) -> str:
    value = _row_metadata(row).get(field)
    if value is None:
        return ""
    return str(value).strip()


def _is_m06_residual_event_governance_accepted_event(row: Mapping[str, Any]) -> bool:
    """Return true only for event kinds accepted by M06/review for chart markers."""

    accepted_values = {
        "accepted",
        "m06_residual_event_governance_accepted",
        "accepted_m06_residual_event_governance_event",
        "accepted_layer4_event_family",
        "production_accepted",
    }
    candidate_fields = (
        "m06_residual_event_governance_status",
        "m06_residual_event_governance_disposition",
        "event_family_status",
        "promotion_status",
        "review_status",
        "status",
    )
    for field in candidate_fields:
        value = _row_text(row, field).lower() or _metadata_text(row, field).lower()
        if value in accepted_values:
            return True
    source_priority = _row_text(row, "source_priority").lower()
    return source_priority in accepted_values


def _event_detail_summary(row: Mapping[str, Any], fallback: str) -> str:
    for field in ("summary", "description", "detail", "coverage_reason"):
        value = _row_text(row, field) or _metadata_text(row, field)
        if value:
            return value
    return fallback


def _event_payloads(rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    market_state_by_date = {
        str(row.get("calendar_date") or ""): str(row.get("session_type") or "unknown")
        for row in rows.get("sessions", [])
        if str(row.get("venue") or "") == "NYSE"
    }
    for row in rows.get("scheduled_events", []):
        if not _is_m06_residual_event_governance_accepted_event(row):
            continue
        at = _event_time(row)
        event_date = str(row.get("event_date") or (at.date().isoformat() if at else ""))
        title = _metadata_text(row, "title") or str(row.get("event_type") or "Accepted event")
        events.append(
            {
                "event_id": str(row.get("event_id")),
                "event_time": _iso_utc(at or datetime.now(UTC)),
                "market_state": market_state_by_date.get(event_date, "unknown"),
                "title": title,
                "lane": "m06_residual_event_governance_accepted_event",
                "family_id": _event_family_id(str(row.get("event_type") or "scheduled")),
                "family_label": str(row.get("event_type") or "scheduled"),
                "event_type": str(row.get("event_type") or "scheduled"),
                "scope": str(row.get("event_scope") or ""),
                "symbol": row.get("symbol"),
                "status": _row_text(row, "m06_residual_event_governance_status") or _metadata_text(row, "m06_residual_event_governance_status") or "accepted",
                "source_priority": str(row.get("source_priority") or ""),
                "summary": _event_detail_summary(row, title),
                "source_name": _metadata_text(row, "source_name") or str(row.get("source_priority") or ""),
                "reference_type": _metadata_text(row, "reference_type") or "artifact",
                "reference": _metadata_text(row, "reference") or str(row.get("raw_artifact_ref") or ""),
            }
        )
    for row in rows.get("event_results", []):
        if not _is_m06_residual_event_governance_accepted_event(row):
            continue
        at = _event_time(row)
        event_date = at.date().isoformat() if at else ""
        events.append(
            {
                "event_id": str(row.get("event_id")),
                "event_time": _iso_utc(at or datetime.now(UTC)),
                "market_state": market_state_by_date.get(event_date, "unknown"),
                "title": "Released event result",
                "lane": "m06_residual_event_governance_accepted_event",
                "family_id": _event_family_id("result"),
                "family_label": "result",
                "event_type": "result",
                "scope": "event",
                "status": _row_text(row, "m06_residual_event_governance_status") or "accepted",
                "source_priority": "result_artifact",
                "summary": "Accepted M06 event result is available.",
                "source_name": "calendar_event_result",
                "reference_type": "artifact",
                "reference": str(row.get("raw_artifact_ref") or ""),
            }
        )
    for row in rows.get("news_events", []):
        if not _is_m06_residual_event_governance_accepted_event(row):
            continue
        at = _event_time(row)
        event_date = str(row.get("event_date") or (at.date().isoformat() if at else ""))
        events.append(
            {
                "event_id": str(row.get("news_event_id")),
                "event_time": _iso_utc(at or datetime.now(UTC)),
                "market_state": market_state_by_date.get(event_date, "unknown"),
                "title": str(row.get("headline") or "News event"),
                "lane": "m06_residual_event_governance_accepted_event",
                "family_id": _event_family_id(str(row.get("event_family_candidate") or "news")),
                "family_label": str(row.get("event_family_candidate") or "news"),
                "event_type": str(row.get("event_family_candidate") or "news"),
                "scope": "news",
                "symbol": row.get("symbol"),
                "status": _row_text(row, "m06_residual_event_governance_status") or str(row.get("dedup_status") or "accepted"),
                "source_priority": str(row.get("source") or ""),
                "summary": str(row.get("headline") or "Accepted M06 news event."),
                "source_name": str(row.get("source") or "calendar_news_event_index"),
                "reference_type": "artifact",
                "reference": str(row.get("raw_artifact_ref") or row.get("interpreted_event_ref") or ""),
            }
        )
    events.sort(key=lambda item: item["event_time"])
    return events[:500]


def _tick_payloads(
    *,
    start_time: datetime,
    end_time: datetime,
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    events: Sequence[Mapping[str, Any]],
    tick_count: int = 21,
) -> list[dict[str, Any]]:
    sessions_by_date = {
        (str(row.get("venue")), str(row.get("calendar_date"))): row for row in rows.get("sessions", [])
    }
    event_times = [_parse_utc(str(event.get("event_time") or "")) for event in events]
    event_times = [value for value in event_times if value is not None]
    ticks: list[dict[str, Any]] = []
    if end_time <= start_time:
        end_time = start_time + timedelta(days=1)
    tick_span = (end_time - start_time) / max(1, tick_count)
    center_index = tick_count // 2
    for index in range(tick_count):
        tick_start = start_time + (tick_span * index)
        tick_end = end_time if index == tick_count - 1 else start_time + (tick_span * (index + 1))
        session = sessions_by_date.get(("NYSE", tick_start.date().isoformat()))
        event_count = sum(1 for value in event_times if tick_start <= value < tick_end)
        ticks.append(
            {
                "tick_start_utc": _iso_utc(tick_start),
                "tick_end_utc": _iso_utc(tick_end),
                "label": tick_start.strftime("%Y-%m"),
                "is_center": index == center_index,
                "market_session_status": str(session.get("session_type") if session else "unknown"),
                "event_count": event_count,
                "chart_bar_count": 0,
            }
        )
    return ticks


def _lane_payloads(*, statuses: Mapping[str, Mapping[str, Any]], rows: Mapping[str, Sequence[Mapping[str, Any]]], storage_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left: list[dict[str, Any]] = []
    model_marker_lane = _model_event_marker_lane(storage_root)
    replay_lane = _replay_state_lane(storage_root)
    right = [
        {"lane_id": "market_session", "label": "Market Session", "status": statuses["calendar_market_session"]["status"], "item_count": len(rows.get("sessions", []))},
        {"lane_id": "scheduled_events", "label": "Scheduled Events", "status": statuses["calendar_scheduled_event"]["status"], "item_count": len(rows.get("scheduled_events", []))},
        {"lane_id": "event_results", "label": "Event Results", "status": statuses["calendar_event_result"]["status"], "item_count": len(rows.get("event_results", []))},
        {"lane_id": "news_event_index", "label": "News Index", "status": statuses["calendar_news_event_index"]["status"], "item_count": len(rows.get("news_events", []))},
        model_marker_lane,
        replay_lane,
    ]
    return left, right


def _model_event_marker_lane(storage_root: Path) -> dict[str, Any]:
    runtime_summary = _read_json(storage_root / "06_dashboard_cache/read_models/execution_realtime_trading_runtime_status.json")
    if not runtime_summary:
        return {"lane_id": "model_event_markers", "label": "Model Event Markers", "status": "missing", "item_count": 0}
    active_pointer = runtime_summary.get("chart_payload", {}).get("active_model_pointer", {})
    if isinstance(active_pointer, Mapping) and active_pointer.get("active_model_config_present"):
        return {"lane_id": "model_event_markers", "label": "Model Event Markers", "status": "populated", "item_count": 1}
    return {"lane_id": "model_event_markers", "label": "Model Event Markers", "status": "empty", "item_count": 0}


def _replay_state_lane(storage_root: Path) -> dict[str, Any]:
    replay_root = storage_root / "05_replay_datasets"
    if not replay_root.exists():
        return {"lane_id": "replay_state", "label": "Replay State", "status": "missing", "item_count": 0}
    item_count = sum(1 for path in replay_root.rglob("*") if path.is_file())
    return {
        "lane_id": "replay_state",
        "label": "Replay State",
        "status": "populated" if item_count else "empty",
        "item_count": item_count,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _chart_bars(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for row in rows:
        bars.append(
            {
                "symbol": str(row.get("symbol") or ""),
                "timeframe": str(row.get("timeframe") or ""),
                "bucket_start": _iso_utc(_parse_utc(str(row.get("bucket_start") or "")) or datetime.now(UTC)),
                "bucket_end": _iso_utc(_parse_utc(str(row.get("bucket_end") or "")) or datetime.now(UTC)),
                "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0),
                "low": float(row.get("low") or 0),
                "close": float(row.get("close") or 0),
                "volume": float(row.get("volume") or 0),
                "bar_count": int(row.get("bar_count") or 0),
                "source": str(row.get("chart_source") or ""),
            }
        )
    return bars


def _available_chart_symbols(chart_bars: Sequence[Mapping[str, Any]]) -> list[str]:
    symbols = {str(row.get("symbol") or "").strip().upper() for row in chart_bars}
    symbols = {symbol for symbol in symbols if symbol}
    return sorted(symbols.union(DEFAULT_CHART_SYMBOLS))


def _event_family_id(value: str) -> str:
    text = str(value or "unknown").strip().lower()
    output = []
    previous_was_separator = False
    for character in text:
        if character.isalnum():
            output.append(character)
            previous_was_separator = False
        elif not previous_was_separator:
            output.append("_")
            previous_was_separator = True
    normalized = "".join(output).strip("_")
    return normalized or "unknown"


def _event_market_state(event: Mapping[str, Any], ticks: Sequence[Mapping[str, Any]]) -> str:
    explicit = str(event.get("market_state") or "").strip()
    if explicit:
        return explicit
    event_time = _parse_utc(str(event.get("event_time") or ""))
    if event_time is None:
        return "unknown"
    for tick in ticks:
        tick_start = _parse_utc(str(tick.get("tick_start_utc") or ""))
        tick_end = _parse_utc(str(tick.get("tick_end_utc") or ""))
        if tick_start is not None and tick_end is not None and tick_start <= event_time < tick_end:
            return str(tick.get("market_session_status") or "unknown")
    return "unknown"


def _event_bar_return(event: Mapping[str, Any], bars: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    event_time = _parse_utc(str(event.get("event_time") or ""))
    if event_time is None:
        return {}
    returns: dict[str, dict[str, float]] = {}
    for bar in bars:
        if str(bar.get("timeframe") or "") != "1D":
            continue
        start = _parse_utc(str(bar.get("bucket_start") or ""))
        end = _parse_utc(str(bar.get("bucket_end") or ""))
        if start is None or end is None or not (start <= event_time < end):
            continue
        open_price = float(bar.get("open") or 0)
        close_price = float(bar.get("close") or 0)
        if open_price <= 0:
            continue
        symbol = str(bar.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        returns[symbol] = {
            "same_bar_return_pct": ((close_price - open_price) / open_price) * 100,
            "volume": float(bar.get("volume") or 0),
        }
    return returns


def _mean(values: Sequence[float]) -> float | None:
    clean = [value for value in values if isinstance(value, (int, float))]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _event_family_payloads(
    *,
    events: Sequence[Mapping[str, Any]],
    ticks: Sequence[Mapping[str, Any]],
    chart_bars: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for event in events:
        family_id = str(event.get("family_id") or _event_family_id(str(event.get("event_type") or event.get("title") or "unknown")))
        family = families.setdefault(
            family_id,
            {
                "family_id": family_id,
                "family_label": str(event.get("family_label") or event.get("event_type") or family_id),
                "event_type": str(event.get("event_type") or family_id),
                "occurrence_count": 0,
                "market_state_counts": Counter(),
                "scope_counts": Counter(),
                "symbol_counts": Counter(),
                "source_counts": Counter(),
                "first_seen_utc": None,
                "last_seen_utc": None,
                "_returns": {},
            },
        )
        event_time = str(event.get("event_time") or "")
        family["occurrence_count"] += 1
        family["market_state_counts"][_event_market_state(event, ticks)] += 1
        family["scope_counts"][str(event.get("scope") or "unknown")] += 1
        family["symbol_counts"][str(event.get("symbol") or "market")] += 1
        family["source_counts"][str(event.get("source_name") or "unknown")] += 1
        if event_time and (family["first_seen_utc"] is None or event_time < family["first_seen_utc"]):
            family["first_seen_utc"] = event_time
        if event_time and (family["last_seen_utc"] is None or event_time > family["last_seen_utc"]):
            family["last_seen_utc"] = event_time
        for symbol, values in _event_bar_return(event, chart_bars).items():
            symbol_returns = family["_returns"].setdefault(symbol, {"returns": [], "volumes": []})
            symbol_returns["returns"].append(values["same_bar_return_pct"])
            symbol_returns["volumes"].append(values["volume"])

    payloads: list[dict[str, Any]] = []
    for family in families.values():
        return_statistics = []
        for symbol in sorted(family["_returns"]):
            returns = family["_returns"][symbol]["returns"]
            volumes = family["_returns"][symbol]["volumes"]
            return_statistics.append(
                {
                    "symbol": symbol,
                    "sample_count": len(returns),
                    "average_same_bar_return_pct": _mean(returns),
                    "positive_rate": (sum(1 for value in returns if value > 0) / len(returns)) if returns else None,
                    "average_volume": _mean(volumes),
                }
            )
        payloads.append(
            {
                "family_id": family["family_id"],
                "family_label": family["family_label"],
                "event_type": family["event_type"],
                "occurrence_count": family["occurrence_count"],
                "first_seen_utc": family["first_seen_utc"],
                "last_seen_utc": family["last_seen_utc"],
                "market_state_counts": dict(sorted(family["market_state_counts"].items())),
                "scope_counts": dict(sorted(family["scope_counts"].items())),
                "symbol_counts": dict(sorted(family["symbol_counts"].items())),
                "source_counts": dict(sorted(family["source_counts"].items())),
                "return_statistics": return_statistics,
            }
        )
    return sorted(payloads, key=lambda item: (-int(item["occurrence_count"]), str(item["family_label"])))


def build_temporal_explorer_summary(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    generated_at_utc: str | None = None,
    center_time_utc: str | None = None,
    frame: str = DEFAULT_FRAME,
    sql_rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    substrate_status: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at_utc = generated_at_utc or now_utc()
    frame = frame if frame in SUPPORTED_FRAMES else DEFAULT_FRAME
    replay_start_month, replay_end_month = _replay_window_from_progress_summary(Path(storage_root)) or (
        DEFAULT_REPLAY_START_MONTH,
        DEFAULT_REPLAY_END_MONTH,
    )
    if center_time_utc:
        center_time = _parse_utc(center_time_utc) or _parse_utc(generated_at_utc) or datetime.now(UTC)
        window_start = center_time - timedelta(days=DEFAULT_CENTER_LOOKBACK_DAYS)
        window_end = center_time + timedelta(days=DEFAULT_CENTER_LOOKAHEAD_DAYS)
        window_label = "custom_center_window"
    else:
        window_start, window_end = _window_from_months(replay_start_month, replay_end_month)
        center_time = window_start + ((window_end - window_start) / 2)
        window_label = "model_group_replay_window"
    statuses = dict(substrate_status or _table_statuses())
    rows = dict(sql_rows or _fetch_sql_rows(start_time=window_start, end_time=window_end, frame=frame))
    events = _event_payloads(rows)
    ticks = _tick_payloads(start_time=window_start, end_time=window_end, rows=rows, events=events)
    left_lanes, right_lanes = _lane_payloads(statuses=statuses, rows=rows, storage_root=Path(storage_root))
    chart_bars = _chart_bars(rows.get("chart_bars", []))
    event_families = _event_family_payloads(events=events, ticks=ticks, chart_bars=chart_bars)
    chart_from_source_bars = any(str(row.get("chart_source") or "") == "source_bar_sql" for row in rows.get("chart_bars", []))
    populated_tables = sum(1 for status in statuses.values() if status.get("status") == "populated")
    event_counts = Counter(event["lane"] for event in events)
    status = "ready" if populated_tables else "empty"
    if any(status.get("status") == "unavailable" for status in statuses.values()):
        status = "degraded"
    return {
        "contract_type": TEMPORAL_EXPLORER_SUMMARY_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": status,
        "severity": "info" if status == "ready" else "medium",
        "summary": f"Events attention pool has {len(events)} certified event-family markers, {len(chart_bars)} ETF chart bars across the replay window, and {populated_tables} populated context tables.",
        "chart_payload": {
            "viewport": {
                "center_time_utc": _iso_utc(center_time),
                "frame": frame,
                "available_frames": list(SUPPORTED_FRAMES),
                "start_utc": _iso_utc(window_start),
                "end_utc": _iso_utc(window_end),
                "window_kind": window_label,
                "replay_start_month": replay_start_month,
                "replay_end_month": replay_end_month,
            },
            "timewheel_ticks": ticks,
            "left_lanes": left_lanes,
            "right_lanes": right_lanes,
            "events": events,
            "event_families": event_families,
            "counts": {"by_lane": dict(sorted(event_counts.items())), "total_events": len(events)},
            "chart": {
                "symbol": "SPY",
                "timeframe": _chart_timeframe(frame),
                "available_symbols": _available_chart_symbols(rows.get("chart_bars", [])),
                "available_timeframes": [_chart_timeframe(value) for value in SUPPORTED_FRAMES],
                "status": "populated" if chart_bars else "not_populated",
                "bars": chart_bars,
                "role": "source_bar_visualization_not_training_truth" if chart_from_source_bars else "visualization_cache_not_training_truth",
            },
            "substrate_status": statuses,
        },
        "profile_refs": [
            {"registry_ref": "TEMPORAL_EXPLORER_SUMMARY", "field": "contract_type"},
            {"registry_ref": "CHART_OHLCV_CACHE", "field": "chart.role"},
        ],
        "issue_refs": [],
        "diagnostic_refs": [
            {"ref_type": "temporal_substrate_tables", "statuses": statuses},
            {"ref_type": "timewheel_visible_event_markers", "count": len(events)},
        ],
        "lineage_refs": [
            {"contract_type": "calendar_day", "included": True},
            {"contract_type": "calendar_market_session", "included": True},
            {"contract_type": "calendar_scheduled_event", "included": True},
            {"contract_type": "calendar_event_result", "included": True},
            {"contract_type": "calendar_news_event_index", "included": True},
            {"contract_type": "chart_ohlcv_cache", "included": True},
        ],
        "freshness": {"class": "temporal_explorer_snapshot", "status": "fresh", "stale_after_seconds": 3600},
        "schema_ref": TEMPORAL_EXPLORER_SCHEMA_REF,
    }


def refresh_temporal_explorer_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    storage_root = Path(storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    payload = build_temporal_explorer_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=TEMPORAL_EXPLORER_SUMMARY_CONTRACT)
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": TEMPORAL_EXPLORER_SUMMARY_CONTRACT,
        "materialized": materialized.index_row,
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


def write_temporal_explorer_summary(payload: Mapping[str, Any], *, output: TextIO) -> None:
    json.dump(dict(payload), output, indent=2, sort_keys=True)
    output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or refresh temporal_explorer_summary.")
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--refresh", action="store_true", help="Materialize the summary under storage/06_dashboard_cache.")
    args = parser.parse_args(argv)
    if args.refresh:
        json.dump(refresh_temporal_explorer_summary_read_model(storage_root=args.storage_root), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    write_temporal_explorer_summary(build_temporal_explorer_summary(storage_root=args.storage_root), output=sys.stdout)
    return 0


__all__ = [
    "TEMPORAL_EXPLORER_SUMMARY_CONTRACT",
    "build_temporal_explorer_summary",
    "refresh_temporal_explorer_summary_read_model",
    "write_temporal_explorer_summary",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
