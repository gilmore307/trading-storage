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
            runtime_summary = storage_root / "06_dashboard_cache/read_models/execution_realtime_trading_runtime_status.json"
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
                            "metadata_json": {"title": "US CPI release", "summary": "Accepted CPI event family.", "m03_event_effect_model_status": "accepted"},
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
                            "chart_source": "source_bar_sql",
                        }
                    ],
                },
            )
            self.assertEqual(validate_dashboard_read_model(payload), TEMPORAL_EXPLORER_SUMMARY_CONTRACT)
            chart = payload["chart_payload"]
            self.assertEqual(chart["viewport"]["frame"], "1D")
            self.assertEqual(len(chart["timewheel_ticks"]), 21)
            self.assertEqual(len(chart["events"]), 1)
            self.assertEqual(chart["events"][0]["lane"], "m03_event_effect_model_accepted_event")
            self.assertEqual(chart["events"][0]["family_id"], "cpi_release")
            self.assertEqual(chart["events"][0]["title"], "US CPI release")
            self.assertEqual(chart["events"][0]["summary"], "Accepted CPI event family.")
            self.assertEqual(len(chart["event_families"]), 1)
            self.assertEqual(chart["event_families"][0]["family_id"], "cpi_release")
            self.assertEqual(chart["event_families"][0]["occurrence_count"], 1)
            self.assertEqual(chart["event_families"][0]["market_state_counts"], {"regular": 1})
            self.assertEqual(chart["event_families"][0]["return_statistics"][0]["symbol"], "SPY")
            self.assertAlmostEqual(chart["event_families"][0]["return_statistics"][0]["average_same_bar_return_pct"], 1.0)
            self.assertEqual(chart["chart"]["status"], "populated")
            self.assertEqual(chart["chart"]["role"], "source_bar_visualization_not_training_truth")
            self.assertEqual(chart["chart"]["bars"][0]["source"], "source_bar_sql")
            self.assertIn("SPY", chart["chart"]["available_symbols"])
            self.assertEqual(chart["left_lanes"], [])
            lanes = {lane["lane_id"]: lane for lane in chart["right_lanes"]}
            self.assertNotIn("market_state", lanes)
            self.assertEqual(lanes["model_event_markers"]["status"], "empty")
            self.assertEqual(lanes["replay_state"]["status"], "empty")

    def test_uses_replay_window_from_task_progress_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            progress_summary = storage_root / "06_dashboard_cache/read_models/historical_task_progress_summary.json"
            progress_summary.parent.mkdir(parents=True)
            progress_summary.write_text(
                json.dumps(
                    {
                        "chart_payload": {
                            "task_timeline": [
                                {
                                    "detail": {
                                        "replay_window": {
                                            "unit_kind": "model_group_replay_window",
                                            "start_month": "2021-01",
                                            "end_month": "2026-01",
                                        }
                                    }
                                }
                            ]
                        }
                    }
                )
            )
            statuses = {
                "calendar_day": {"status": "populated", "row_count": 2},
                "calendar_market_session": {"status": "populated", "row_count": 2},
                "calendar_scheduled_event": {"status": "empty", "row_count": 0},
                "calendar_event_result": {"status": "empty", "row_count": 0},
                "calendar_news_event_index": {"status": "empty", "row_count": 0},
                "chart_ohlcv_cache": {"status": "empty", "row_count": 0},
            }
            payload = build_temporal_explorer_summary(
                storage_root=storage_root,
                generated_at_utc="2026-06-30T00:00:00Z",
                substrate_status=statuses,
                sql_rows={
                    "sessions": [],
                    "scheduled_events": [],
                    "event_results": [],
                    "news_events": [],
                    "chart_bars": [],
                },
            )
            viewport = payload["chart_payload"]["viewport"]
            self.assertEqual(viewport["window_kind"], "model_group_replay_window")
            self.assertEqual(viewport["replay_start_month"], "2021-01")
            self.assertEqual(viewport["replay_end_month"], "2026-01")
            self.assertEqual(viewport["start_utc"], "2021-01-01T05:00:00Z")
            self.assertEqual(viewport["end_utc"], "2026-02-01T05:00:00Z")

    def test_event_families_include_modelability_evidence_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            packet_path = (
                storage_root
                / "02_control_plane/runtime/model_03_event_family_modelability/evidence_packets/cpi_release/aapl/2021_01_2025_12/evidence_packet.json"
            )
            packet_path.parent.mkdir(parents=True)
            packet_path.write_text(
                json.dumps(
                    {
                        "contract_type": "model_03_event_family_modelability_evidence_packet",
                        "event_family_id": "cpi_release",
                        "target_symbol": "AAPL",
                        "start_month": "2021-01",
                        "end_month": "2025-12",
                        "readiness_status": "blocked_missing_modelability_gates",
                        "required_next_action": "build_modelability_control_gate_evidence",
                        "observations": [
                            {
                                "event_ref": "scheduled-macro-release://cpi-20210113",
                                "event_time": "2021-01-13T08:30:00-05:00",
                                "event_title": "CPI release",
                                "event_summary": "United States CPI release",
                                "affected_scope": "macro",
                                "source_name": "calendar_scheduled_event",
                                "normalized_event_parameters": {
                                    "event_kind": "cpi_release",
                                    "event_scope": "macro",
                                    "source_category": "scheduled_macro_release",
                                    "symbol": "CPI",
                                },
                            }
                        ],
                    }
                )
            )
            payload = build_temporal_explorer_summary(
                storage_root=storage_root,
                generated_at_utc="2026-06-30T00:00:00Z",
                substrate_status={
                    "calendar_day": {"status": "empty", "row_count": 0},
                    "calendar_market_session": {"status": "empty", "row_count": 0},
                    "calendar_scheduled_event": {"status": "empty", "row_count": 0},
                    "calendar_event_result": {"status": "empty", "row_count": 0},
                    "calendar_news_event_index": {"status": "empty", "row_count": 0},
                    "chart_ohlcv_cache": {"status": "empty", "row_count": 0},
                },
                sql_rows={
                    "sessions": [],
                    "scheduled_events": [],
                    "event_results": [],
                    "news_events": [],
                    "chart_bars": [],
                },
            )
            chart = payload["chart_payload"]
            self.assertEqual(len(chart["events"]), 1)
            self.assertEqual(chart["events"][0]["lane"], "model_03_event_family_modelability_observation")
            self.assertEqual(chart["events"][0]["family_id"], "cpi_release")
            self.assertEqual(chart["events"][0]["status"], "blocked_missing_modelability_gates")
            self.assertEqual(len(chart["event_families"]), 1)
            self.assertEqual(chart["event_families"][0]["family_id"], "cpi_release")

    def test_refresh_materializes_temporal_explorer_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "storage"
            receipt = refresh_temporal_explorer_summary_read_model(storage_root=root)
            self.assertEqual(receipt["refreshed_contract_type"], TEMPORAL_EXPLORER_SUMMARY_CONTRACT)
            self.assertTrue((root / "06_dashboard_cache/read_models/temporal_explorer_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
