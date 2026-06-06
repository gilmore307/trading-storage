from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_execution_runtime import (
    EXECUTION_RUNTIME_STATUS_CONTRACT,
    build_execution_runtime_status_read_model,
    refresh_execution_runtime_status_read_model,
)


class ExecutionRuntimeStatusReadModelTests(unittest.TestCase):
    def test_builds_missing_status_read_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_execution_runtime_status_read_model(
                status_path=Path(tmp) / "missing.json",
                generated_at_utc="2026-05-20T00:00:00Z",
            )

        self.assertEqual(payload["contract_type"], EXECUTION_RUNTIME_STATUS_CONTRACT)
        self.assertEqual(payload["status"], "not_available")
        self.assertEqual(payload["chart_payload"]["websocket_latest_route"], "/ws/read-models/execution_realtime_trading_runtime_status/latest")

    def test_builds_waiting_status_from_execution_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "runtime_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT,
                        "runtime_status": "waiting_for_promoted_model",
                        "next_gate": "write_active_model_config_after_promotion",
                        "active_model_pointer": {"active_model_pointer_status": "missing_active_model_pointer"},
                        "interfaces_connected": {"active_model_config_write": True},
                        "allowed_actions": {"broker_execution_allowed": False},
                        "required_runtime_inputs": [],
                        "provider_calls_performed": 0,
                        "model_activation_performed": False,
                        "broker_order_construction_performed": False,
                        "broker_calls_performed": 0,
                        "account_mutation_performed": False,
                    }
                ),
                encoding="utf-8",
            )
            payload = build_execution_runtime_status_read_model(
                status_path=status_path,
                generated_at_utc="2026-05-20T00:00:00Z",
            )

        self.assertEqual(payload["status"], "waiting_for_promoted_model")
        self.assertEqual(payload["severity"], "info")
        self.assertFalse(payload["chart_payload"]["safety"]["account_mutation_performed"])

    def test_refresh_materializes_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT,
                        "runtime_status": "waiting_for_promoted_model",
                        "provider_calls_performed": 0,
                        "model_activation_performed": False,
                        "broker_order_construction_performed": False,
                        "broker_calls_performed": 0,
                        "account_mutation_performed": False,
                    }
                ),
                encoding="utf-8",
            )
            receipt = refresh_execution_runtime_status_read_model(storage_root=root / "storage", status_path=status_path)
            latest = root / "storage/06_dashboard_cache/read_models/execution_realtime_trading_runtime_status.json"
            self.assertEqual(receipt["refreshed_contract_type"], EXECUTION_RUNTIME_STATUS_CONTRACT)
            self.assertTrue(latest.exists())


if __name__ == "__main__":
    unittest.main()
