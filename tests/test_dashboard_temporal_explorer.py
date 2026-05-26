import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_read_models import validate_dashboard_read_model
from trading_storage.dashboard_temporal_explorer import (
    TEMPORAL_EXPLORER_SUMMARY_CONTRACT,
    build_temporal_explorer_summary,
    refresh_temporal_explorer_summary_read_model,
)


class DashboardTemporalExplorerTests(unittest.TestCase):
    def test_builds_timewheel_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            runtime_summary = storage_root / "06_dashboard_cache/read_models/execution_realtime_trading_runtime_status/latest.json"
            runtime_summary.parent.mkdir(parents=True)
            runtime_summary.write_text(
                json.dumps(
                    {
                        "chart_payload": {
                            "active_model_pointer": {
                                "active_model_config_present": False,
                            }
                        }
                    }
                )
            )
            (storage_root / "05_replay_datasets").mkdir(parents=True)
            statuses = {
                "calendar_day": {"status": "populated", "row_count": 2},
                "calendar_market_session": {"status": "populated", "row_count": 2},
                "calendar_scheduled_event": {"status": "populated", "row_count": 1},
                "calendar_event_result": {"status": "empty", "row_count": 0},
                "calendar_news_event_index": {"status": "empty", "row_count": 0},
                "chart_ohlcv_cache": {"status": "populated", "row_count": 1},
            }
            payload = build_temporal_explorer_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-26T12:00:00Z",
                center_time_utc="2026-05-26T12:00:00Z",
                substrate_status=statuses,
                sql_rows={
                    "sessions": [{"venue": "NYSE", "calendar_date": "2026-05-26", "session_type": "regular"}],
                    "scheduled_events": [
                        {
                            "event_id": "cpi-20260526",
                            "event_time": "2026-05-26T12:30:00Z",
                            "event_date": "2026-05-26",
                            "event_type": "cpi_release",
                            "event_scope": "macro",
                            "source_priority": "approved_calendar",
                            "metadata_json": {"title": "US CPI release", "summary": "Accepted CPI event family.", "layer10_status": "accepted"},
                        },
                        {
                            "event_id": "ordinary-macro-20260526",
                            "event_time": "2026-05-26T13:30:00Z",
                            "event_date": "2026-05-26",
                            "event_type": "macro_data",
                            "event_scope": "macro",
                            "source_priority": "approved_calendar",
                        }
                    ],
                    "event_results": [],
                    "news_events": [],
                    "chart_bars": [
                        {
                            "symbol": "SPY",
                            "timeframe": "1D",
                            "bucket_start": "2026-05-26T00:00:00Z",
                            "bucket_end": "2026-05-27T00:00:00Z",
                            "open": 100,
                            "high": 102,
                            "low": 99,
                            "close": 101,
                            "volume": 1000,
                            "bar_count": 1,
                        }
                    ],
                },
            )
            self.assertEqual(validate_dashboard_read_model(payload), TEMPORAL_EXPLORER_SUMMARY_CONTRACT)
            chart = payload["chart_payload"]
            self.assertEqual(chart["viewport"]["frame"], "1D")
            self.assertEqual(len(chart["timewheel_ticks"]), 21)
            self.assertEqual(len(chart["events"]), 1)
            self.assertEqual(chart["events"][0]["lane"], "layer10_accepted_event")
            self.assertEqual(chart["events"][0]["title"], "US CPI release")
            self.assertEqual(chart["events"][0]["summary"], "Accepted CPI event family.")
            self.assertEqual(chart["chart"]["status"], "populated")
            self.assertIn("SPY", chart["chart"]["available_symbols"])
            self.assertEqual(chart["left_lanes"], [])
            lanes = {lane["lane_id"]: lane for lane in chart["right_lanes"]}
            self.assertNotIn("market_state", lanes)
            self.assertEqual(lanes["model_event_markers"]["status"], "empty")
            self.assertEqual(lanes["replay_state"]["status"], "empty")

    def test_refresh_materializes_temporal_explorer_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "storage"
            receipt = refresh_temporal_explorer_summary_read_model(storage_root=root)
            self.assertEqual(receipt["refreshed_contract_type"], TEMPORAL_EXPLORER_SUMMARY_CONTRACT)
            self.assertTrue((root / "06_dashboard_cache/read_models/temporal_explorer_summary/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
