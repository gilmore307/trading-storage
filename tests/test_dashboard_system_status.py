from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_storage.dashboard_system_status import (
    CURRENT_SYSTEM_STATUS_CONTRACT,
    _dashboard_source_outputs,
    _historical_scheduler_runtime_throughput,
    _mark_missing_event_outputs_waiting,
    _mark_parked_execution_outputs,
    _mark_source_outputs_not_started,
    _systemd_unit_is_healthy,
    _trading_systemd_unit_names,
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
            self.assertEqual(chart["api"]["http_latest_route"], "/api/read-models/<contract_type>/latest")
            self.assertEqual(chart["api"]["websocket_latest_route"], "/ws/read-models/<contract_type>/latest")
            self.assertIn("trading-dashboard-web.service", {service["unit"] for service in chart["services"]})
            self.assertTrue(all("unit_kind" in service and "load_state" in service for service in chart["services"]))
            self.assertEqual(
                [api["name"] for api in chart["apis"]],
                [
                    "Alpaca Market Data API",
                    "OKX Market Data API",
                    "ThetaData Options API",
                    "Trading Economics Calendar Source",
                ],
            )
            self.assertTrue(all("status" in api and "healthy" in api for api in chart["apis"]))
            self.assertEqual(chart["source_connections"], chart["apis"])
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
            self.assertEqual(chart["refresh"]["cadence_seconds"], 60)
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
                    "Execution Runtime Status",
                    "Latest Realtime Monitor Receipt",
                    "Latest Realtime Monitor Cycle",
                    "Trading Economics Canonical Source Receipt",
                    "Trading Economics Canonical Source Events",
                    "Dashboard Read Model Index",
                    "Status Read Model",
                    "Historical Task Progress Read Model",
                    "Realtime Signal Summary Read Model",
                    "Temporal Explorer Read Model",
                    "Execution Runtime Read Model",
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
            runtime = manager_root / "runtime"
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
                manager_storage_root=manager_root,
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
            runtime = manager_root / "runtime"
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
            outputs = _dashboard_source_outputs(storage_root=manager_root, manager_storage_root=manager_root, now_epoch=0)
            active_workflow = next(output for output in outputs if output["label"] == "Active Workflow State")
            self.assertEqual(active_workflow["latest_updated_at_utc"], "2026-05-14T00:01:00Z")
            self.assertEqual(active_workflow["freshness_class"], "event_driven")

    def test_source_outputs_do_not_use_unqualified_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager_root = Path(tmp)
            runtime = manager_root / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "model_training_workflow_state.json").write_text(
                json.dumps({"updated_utc": "2026-05-10T00:00:00Z"}),
                encoding="utf-8",
            )

            outputs = _dashboard_source_outputs(storage_root=manager_root, manager_storage_root=manager_root, now_epoch=0)
            active_workflow = next(output for output in outputs if output["label"] == "Active Workflow State")
            self.assertEqual(active_workflow["status"], "missing")
            self.assertIsNone(active_workflow["latest_updated_at_utc"])

    def test_missing_runtime_outputs_are_not_started_when_scheduler_is_stopped(self) -> None:
        outputs = _mark_source_outputs_not_started(
            [
                {
                    "label": "Historical Scheduler State",
                    "kind": "manager_scheduler_state",
                    "status": "missing",
                    "exists": False,
                    "age_seconds": None,
                    "latest_updated_at_utc": None,
                    "freshness_class": "heartbeat",
                    "freshness_note": "old note",
                }
            ]
        )

        self.assertEqual(outputs[0]["status"], "not_started")
        self.assertIn("Historical training is stopped", outputs[0]["freshness_note"])

    def test_missing_event_driven_outputs_are_not_failures_while_scheduler_runs(self) -> None:
        outputs = _mark_missing_event_outputs_waiting(
            [
                {
                    "label": "Latest Stage Run Output",
                    "kind": "manager_stage_run_dashboard",
                    "status": "missing",
                    "exists": False,
                    "age_seconds": None,
                    "latest_updated_at_utc": None,
                    "freshness_class": "event_driven",
                    "freshness_note": "old note",
                },
                {
                    "label": "Historical Scheduler State",
                    "kind": "manager_scheduler_state",
                    "status": "missing",
                    "exists": False,
                    "age_seconds": None,
                    "latest_updated_at_utc": None,
                    "freshness_class": "heartbeat",
                    "freshness_note": "old note",
                },
            ]
        )

        self.assertEqual(outputs[0]["status"], "not_recorded_yet")
        self.assertIn("Event-driven source output", outputs[0]["freshness_note"])
        self.assertEqual(outputs[1]["status"], "missing")

    def test_execution_outputs_are_parked_when_realtime_units_are_inactive(self) -> None:
        outputs = _mark_parked_execution_outputs(
            [
                {
                    "label": "Latest Realtime Monitor Cycle",
                    "kind": "execution_realtime_monitor_cycle",
                    "status": "available",
                    "exists": True,
                    "age_seconds": 100,
                    "latest_updated_at_utc": "2026-05-26T19:24:19Z",
                    "freshness_class": "heartbeat",
                    "freshness_note": "old note",
                },
                {
                    "label": "Status Read Model",
                    "kind": "storage_dashboard_current_status_latest",
                    "status": "available",
                    "exists": True,
                    "age_seconds": 1,
                    "latest_updated_at_utc": "2026-06-05T03:00:00Z",
                    "freshness_class": "heartbeat",
                    "freshness_note": "old note",
                },
            ],
            services=[
                {
                    "unit": "trading-execution-realtime-monitor-loop.service",
                    "active_state": "inactive",
                }
            ],
        )

        self.assertEqual(outputs[0]["status"], "parked")
        self.assertIn("Execution realtime services are not active", outputs[0]["freshness_note"])
        self.assertEqual(outputs[1]["status"], "available")

    def test_execution_outputs_remain_available_when_realtime_unit_is_active(self) -> None:
        outputs = _mark_parked_execution_outputs(
            [
                {
                    "label": "Latest Realtime Monitor Cycle",
                    "kind": "execution_realtime_monitor_cycle",
                    "status": "available",
                    "exists": True,
                    "age_seconds": 1,
                    "latest_updated_at_utc": "2026-06-05T03:00:00Z",
                    "freshness_class": "heartbeat",
                    "freshness_note": "old note",
                }
            ],
            services=[
                {
                    "unit": "trading-execution-realtime-monitor-loop.service",
                    "active_state": "active",
                }
            ],
        )

        self.assertEqual(outputs[0]["status"], "available")

    def test_refresh_materializes_current_system_status_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            receipt = refresh_current_system_status_read_model(storage_root=storage_root)
            self.assertEqual(receipt["refreshed_contract_type"], CURRENT_SYSTEM_STATUS_CONTRACT)
            latest_path = storage_root / "06_dashboard_cache/read_models/current_system_status_summary/latest.json"
            self.assertTrue(latest_path.exists())
            latest = json.loads(latest_path.read_text())
            self.assertEqual(latest["contract_type"], CURRENT_SYSTEM_STATUS_CONTRACT)

    def test_refresh_creates_missing_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "missing-storage-root"
            receipt = refresh_current_system_status_read_model(storage_root=storage_root)
            self.assertTrue(storage_root.exists())
            self.assertEqual(receipt["refreshed_contract_type"], CURRENT_SYSTEM_STATUS_CONTRACT)

    def test_refresh_cadence_uses_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            old_value = os.environ.get("TRADING_STORAGE_REFRESH_CADENCE_SECONDS")
            os.environ["TRADING_STORAGE_REFRESH_CADENCE_SECONDS"] = "17"
            try:
                payload = build_current_system_status_summary(storage_root=storage_root)
            finally:
                if old_value is None:
                    os.environ.pop("TRADING_STORAGE_REFRESH_CADENCE_SECONDS", None)
                else:
                    os.environ["TRADING_STORAGE_REFRESH_CADENCE_SECONDS"] = old_value
            self.assertEqual(payload["chart_payload"]["refresh"]["cadence_seconds"], 17)

    def test_systemd_unit_inventory_uses_all_trading_unit_files(self) -> None:
        output = "\n".join(
            [
                "trading-dashboard-web.service enabled enabled",
                "trading-data-te-calendar-refresh.timer enabled enabled",
                "trading-execution-realtime-runtime-check.path enabled enabled",
                "unrelated.service enabled enabled",
            ]
        )
        with patch("trading_storage.dashboard_system_status._run_text", return_value=(0, output)):
            units = _trading_systemd_unit_names()

        self.assertEqual(
            units,
            [
                "trading-dashboard-web.service",
                "trading-data-te-calendar-refresh.timer",
                "trading-execution-realtime-runtime-check.path",
            ],
        )

    def test_successful_auto_restart_service_is_healthy_between_cycles(self) -> None:
        self.assertTrue(
            _systemd_unit_is_healthy(
                unit_kind="service",
                unit_type="simple",
                load_state="loaded",
                active_state="activating",
                enabled_state="enabled",
                substate="auto-restart",
                result="success",
            )
        )

    def test_failed_auto_restart_service_is_unhealthy(self) -> None:
        self.assertFalse(
            _systemd_unit_is_healthy(
                unit_kind="service",
                unit_type="simple",
                load_state="loaded",
                active_state="activating",
                enabled_state="enabled",
                substate="auto-restart",
                result="exit-code",
            )
        )


if __name__ == "__main__":
    unittest.main()
