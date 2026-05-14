from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_system_status import (
    CURRENT_SYSTEM_STATUS_CONTRACT,
    _dashboard_source_outputs,
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
            self.assertIn("apis", chart)
            self.assertIn("services", chart)
            self.assertIn("parallelism", chart)
            self.assertIn("source_outputs", chart)
            self.assertEqual(chart["api"]["websocket_latest_route"], "/ws/read-models/<contract_type>/latest")
            self.assertEqual(
                [api["name"] for api in chart["apis"]],
                ["Alpaca Market Data API", "OKX Market Data API", "ThetaData Options API"],
            )
            self.assertTrue(all("status" in api and "healthy" in api for api in chart["apis"]))
            server = chart["server"]
            self.assertIn("cpu_usage_percent", server)
            self.assertIn("memory_usage_percent", server)
            self.assertIn("network_download_kbps", server)
            self.assertIn("network_upload_kbps", server)
            parallelism = chart["parallelism"]
            self.assertEqual(parallelism["mode"], "dynamic")
            self.assertGreaterEqual(parallelism["selected_worker_count"], 1)
            self.assertIn("next_request_limit", parallelism)
            self.assertIn("max_worker_count", parallelism)
            self.assertTrue(parallelism["drain_ready_stages"])
            self.assertEqual(parallelism["scheduler_interval_role"], "idle_backstop")
            self.assertIn("drain_max_steps", parallelism)
            self.assertIn("event_refresh_service_unit", parallelism)
            self.assertEqual(
                [output["label"] for output in chart["source_outputs"]],
                [
                    "Historical Scheduler State",
                    "Scheduler Decision Log",
                    "Active Workflow State",
                    "Latest Stage Coverage Output",
                    "Latest Stage Run Output",
                ],
            )
            self.assertTrue(all("latest_updated_at_utc" in output for output in chart["source_outputs"]))
            by_label = {output["label"]: output for output in chart["source_outputs"]}
            self.assertEqual(by_label["Historical Scheduler State"]["freshness_class"], "heartbeat")
            self.assertEqual(by_label["Scheduler Decision Log"]["freshness_class"], "event_driven")
            self.assertEqual(by_label["Active Workflow State"]["freshness_class"], "event_driven")
            self.assertTrue(all("freshness_note" in output for output in chart["source_outputs"]))

    def test_source_outputs_use_active_month_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager_root = Path(tmp)
            runtime = manager_root / "storage/runtime"
            runtime.mkdir(parents=True)
            (runtime / "historical_scheduler_state.json").write_text(
                json.dumps({"start_month": "2020-01", "updated_utc": "2026-05-14T00:00:00Z"}),
                encoding="utf-8",
            )
            (runtime / "model_training_workflow_state.json").write_text(
                json.dumps({"updated_utc": "2026-05-10T00:00:00Z"}),
                encoding="utf-8",
            )
            (runtime / "model_training_workflow_state_2020-01.json").write_text(
                json.dumps({"updated_utc": "2026-05-14T00:01:00Z"}),
                encoding="utf-8",
            )
            outputs = _dashboard_source_outputs(trading_manager_root=manager_root, now_epoch=0)
            active_workflow = next(output for output in outputs if output["label"] == "Active Workflow State")
            self.assertEqual(active_workflow["latest_updated_at_utc"], "2026-05-14T00:01:00Z")
            self.assertEqual(active_workflow["freshness_class"], "event_driven")

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
