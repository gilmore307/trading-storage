from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_realtime_signals import (
    REALTIME_SIGNAL_SUMMARY_CONTRACT,
    build_realtime_signal_summary,
    refresh_realtime_signal_summary_read_model,
)


class RealtimeSignalSummaryTests(unittest.TestCase):
    def test_builds_safe_empty_state_without_monitor_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = build_realtime_signal_summary(
                storage_root=root / "storage",
                execution_root=root / "execution",
                generated_at_utc="2026-05-18T00:00:00Z",
            )

        self.assertEqual(payload["contract_type"], REALTIME_SIGNAL_SUMMARY_CONTRACT)
        self.assertEqual(payload["status"], "not_started")
        self.assertEqual(payload["severity"], "info")
        self.assertEqual(payload["chart_payload"]["monitor"]["cycle_count"], 0)
        self.assertFalse(payload["chart_payload"]["safety"]["account_mutation_performed"])

    def test_builds_shadow_ready_state_from_latest_loop_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_path = root / "execution/storage/runtime/realtime_monitor/loop_receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(
                json.dumps(
                    {
                        "contract_type": "execution_realtime_monitor_loop_receipt",
                        "loop_status": "completed",
                        "provider_calls_performed": 2,
                        "broker_calls_performed": 0,
                        "model_activation_performed": False,
                        "broker_order_construction_performed": False,
                        "account_mutation_performed": False,
                        "cycle_summaries": [
                            {
                                "cycle_status": "succeeded",
                                "summary": {
                                    "live_observe_status": "observed",
                                    "provider_calls_performed": 2,
                                    "broker_calls_performed": 0,
                                    "model_activation_performed": False,
                                    "broker_order_construction_performed": False,
                                    "account_mutation_performed": False,
                                    "feature_snapshot_readiness": "ready_for_fixture_or_shadow_model_decision_input",
                                    "decision_input_readiness": "ready_for_historical_model_decision_handoff",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_realtime_signal_summary(
                storage_root=root / "storage",
                execution_root=root / "execution",
                generated_at_utc="2026-05-18T00:00:00Z",
            )

        self.assertEqual(payload["status"], "shadow_ready")
        self.assertEqual(payload["chart_payload"]["monitor"]["cycle_count"], 1)
        self.assertEqual(payload["chart_payload"]["safety"]["provider_calls_performed"], 2)
        self.assertEqual(payload["chart_payload"]["readiness"]["decision_input_readiness"], "ready_for_historical_model_decision_handoff")

    def test_refresh_materializes_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = refresh_realtime_signal_summary_read_model(
                storage_root=root / "storage",
                execution_root=root / "execution",
            )

            latest = root / "storage/dashboard/read_models/realtime_signal_summary/latest.json"
            self.assertEqual(receipt["refreshed_contract_type"], REALTIME_SIGNAL_SUMMARY_CONTRACT)
            self.assertTrue(latest.exists())


if __name__ == "__main__":
    unittest.main()
