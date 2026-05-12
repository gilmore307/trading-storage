from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_system_status import (
    CURRENT_SYSTEM_STATUS_CONTRACT,
    build_current_system_status_summary,
    refresh_current_system_status_read_model,
)
from trading_storage.dashboard_read_models import validate_dashboard_read_model


class DashboardSystemStatusTests(unittest.TestCase):
    def test_builds_valid_current_system_status_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            payload = build_current_system_status_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-12T12:00:00Z",
            )
            self.assertEqual(payload["contract_type"], CURRENT_SYSTEM_STATUS_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), CURRENT_SYSTEM_STATUS_CONTRACT)
            chart = payload["chart_payload"]
            self.assertIn("server", chart)
            self.assertIn("api", chart)
            self.assertIn("services", chart)
            self.assertIn("read_models", chart)
            self.assertEqual(chart["api"]["websocket_latest_route"], "/ws/read-models/<contract_type>/latest")

    def test_refresh_materializes_current_system_status_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            receipt = refresh_current_system_status_read_model(storage_root=storage_root)
            self.assertEqual(receipt["refreshed_contract_type"], CURRENT_SYSTEM_STATUS_CONTRACT)
            latest_path = storage_root / "dashboard/read_models/current_system_status_summary/latest.json"
            self.assertTrue(latest_path.exists())
            latest = json.loads(latest_path.read_text())
            self.assertEqual(latest["contract_type"], CURRENT_SYSTEM_STATUS_CONTRACT)


if __name__ == "__main__":
    unittest.main()
