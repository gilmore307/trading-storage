from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_storage.dashboard_event_calendar import (
    EVENT_CALENDAR_SUMMARY_CONTRACT,
    build_event_calendar_summary,
    refresh_event_calendar_summary_read_model,
)
from trading_storage.dashboard_read_models import validate_dashboard_read_model


class DashboardEventCalendarTests(unittest.TestCase):
    def test_builds_event_calendar_summary_from_event_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            te_run = storage_root / "01_source_data/monthly_backfill/trading_economics_calendar_web/2026-05/runs/run/saved"
            te_run.mkdir(parents=True)
            (te_run / "trading_economics_calendar_event.csv").write_text("event_time,event\n", encoding="utf-8")
            (te_run.parent / "completion_receipt.json").write_text('{"generated_at_utc":"2026-05-26T12:00:00Z"}\n', encoding="utf-8")
            rows = [
                {
                    "event_id": "evt_macro",
                    "event_time": "2026-05-28T12:30:00+00:00",
                    "available_time": "2026-05-26T12:00:00Z",
                    "event_category_type": "macro_data",
                    "scope_type": "macro",
                    "title": "GDP Growth Rate QoQ",
                    "source_name": "07_feed_trading_economics_calendar_web",
                    "source_priority": "approved_calendar",
                    "reference_type": "web_url",
                    "reference": "https://tradingeconomics.com/united-states/calendar",
                    "source_artifact_path": str(te_run / "trading_economics_calendar_event.csv"),
                },
                {
                    "event_id": "evt_earnings",
                    "event_time": "2026-05-24T12:00:00+00:00",
                    "available_time": "2026-05-20T12:00:00Z",
                    "event_category_type": "earnings_guidance",
                    "scope_type": "symbol",
                    "symbol": "AAPL",
                    "title": "AAPL earnings release",
                    "source_name": "nasdaq_earnings_calendar",
                    "source_priority": "approved_calendar",
                    "reference_type": "web_url",
                    "reference": "https://api.nasdaq.com/api/calendar/earnings",
                    "source_artifact_path": "/storage/calendar/release_calendar.csv",
                },
            ]

            payload = build_event_calendar_summary(
                storage_root=storage_root,
                rows=rows,
                generated_at_utc="2026-05-26T12:00:00Z",
            )

        self.assertEqual(validate_dashboard_read_model(payload), EVENT_CALENDAR_SUMMARY_CONTRACT)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["chart_payload"]["counts"]["upcoming_events"], 1)
        self.assertEqual(payload["chart_payload"]["counts"]["recent_events"], 1)
        self.assertEqual(payload["chart_payload"]["counts"]["events_with_source_artifact_path"], 2)
        by_family = {row["family_id"]: row for row in payload["chart_payload"]["families"]}
        self.assertEqual(by_family["macro_scheduled_releases"]["status"], "active")
        self.assertEqual(by_family["earnings_scheduled_shells"]["status"], "active")
        self.assertEqual(by_family["option_expiry_windows"]["status"], "not_connected")

    def test_refresh_materializes_event_calendar_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            rows = [
                {
                    "event_id": "evt_macro",
                    "event_time": "2026-05-28T12:30:00+00:00",
                    "available_time": "2026-05-26T12:00:00Z",
                    "event_category_type": "macro_data",
                    "scope_type": "macro",
                    "title": "GDP Growth Rate QoQ",
                    "source_name": "07_feed_trading_economics_calendar_web",
                    "source_priority": "approved_calendar",
                    "reference_type": "web_url",
                    "reference": "https://tradingeconomics.com/united-states/calendar",
                }
            ]
            with patch("trading_storage.dashboard_event_calendar._fetch_event_rows_from_sql", return_value=rows):
                receipt = refresh_event_calendar_summary_read_model(storage_root=storage_root)

            self.assertEqual(receipt["refreshed_contract_type"], EVENT_CALENDAR_SUMMARY_CONTRACT)
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/event_calendar_summary/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
