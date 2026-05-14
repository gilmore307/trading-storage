from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_system_status import (
    CURRENT_SYSTEM_STATUS_CONTRACT,
    _dashboard_source_outputs,
    _historical_scheduler_runtime_throughput,
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
            self.assertIn("runtime_throughput", chart)
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
            runtime_throughput = chart["runtime_throughput"]
            self.assertEqual(runtime_throughput["mode"], "runtime_throughput")
            self.assertIn("month_ingest_worker_count", runtime_throughput)
            self.assertEqual(runtime_throughput["model_worker_count"], 1)
            self.assertIn("completion_rate_per_minute", runtime_throughput)
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

    def test_runtime_throughput_summarizes_recent_decision_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager_root = Path(tmp)
            runtime = manager_root / "storage/runtime"
            runtime.mkdir(parents=True)
            (runtime / "historical_scheduler_decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"now_utc": "2026-05-14T12:00:00+00:00", "decision_status": "executed"}),
                        json.dumps({"now_utc": "2026-05-14T12:00:00+00:00", "decision_status": "executed"}),
                        json.dumps({"now_utc": "2026-05-14T12:01:00+00:00", "decision_status": "backoff"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            throughput = _historical_scheduler_runtime_throughput(
                values={"TRADING_MANAGER_MONTH_INGEST_WORKERS": "3"},
                trading_manager_root=manager_root,
            )

        self.assertEqual(throughput["month_ingest_worker_count"], 3)
        self.assertEqual(throughput["total_worker_count"], 4)
        self.assertEqual(throughput["month_ingest_rounds_per_fold"], 2)
        self.assertEqual(throughput["executed_decision_count"], 2)
        self.assertEqual(throughput["max_completions_per_second"], 2)
        self.assertEqual(throughput["multi_completion_second_count"], 1)

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
