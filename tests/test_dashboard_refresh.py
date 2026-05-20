from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_refresh import (
    HISTORICAL_TASK_PROGRESS_CONTRACT,
    build_historical_task_progress_producer_argv,
    latest_stage_coverage_path,
    refresh_dashboard_read_model_from_producer,
)


def historical_payload() -> dict:
    return {
        "contract_type": HISTORICAL_TASK_PROGRESS_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": "2026-05-12T00:00:00Z",
        "source_system": "trading-manager",
        "status": "ready",
        "severity": "info",
        "summary": "Historical scheduler can continue at the next selected stage.",
        "chart_payload": {
            "current_month": "2016-01",
            "active_stage": "layer_01_market_regime.data_acquisition",
            "progress_percent": 0.0,
            "stage_counts": {"pending": 1},
        },
        "profile_refs": [],
        "issue_refs": [],
        "diagnostic_refs": [],
        "lineage_refs": [{"contract_type": "manager_historical_scheduler_status"}],
        "freshness": {"class": "runtime_status_snapshot", "status": "fresh", "stale_after_seconds": 900},
        "schema_ref": "storage/06_dashboard_cache/schemas/historical_task_progress_summary.schema.json",
    }


class DashboardRefreshTests(unittest.TestCase):
    def test_refresh_runs_producer_and_materializes_historical_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            producer = (
                sys.executable,
                "-c",
                "import json; print(json.dumps(" + json.dumps(historical_payload()) + "))",
            )

            result = refresh_dashboard_read_model_from_producer(
                producer_argv=producer,
                storage_root=storage_root,
                expected_contract_type=HISTORICAL_TASK_PROGRESS_CONTRACT,
            )

            latest_path = storage_root / "06_dashboard_cache" / "read_models" / HISTORICAL_TASK_PROGRESS_CONTRACT / "latest.json"
            self.assertTrue(latest_path.exists())
            self.assertEqual(result.receipt["contract_type"], "dashboard_read_model_refresh_receipt")
            self.assertEqual(result.receipt["refreshed_contract_type"], HISTORICAL_TASK_PROGRESS_CONTRACT)
            self.assertTrue(result.receipt["side_effects"]["storage_dashboard_write"])
            self.assertFalse(result.receipt["side_effects"]["provider_calls"])
            self.assertFalse(result.receipt["side_effects"]["model_activation"])
            self.assertFalse(result.receipt["side_effects"]["broker_execution"])
            self.assertFalse(result.receipt["side_effects"]["account_mutation"])

    def test_builds_manager_producer_command_with_optional_stage_coverage(self):
        argv = build_historical_task_progress_producer_argv(
            trading_manager_root=Path("/example/manager"),
            stage_coverage_path=Path("coverage.json"),
        )

        self.assertIn("/example/manager/scripts/tasks/build_historical_task_progress_summary.py", argv[1])
        self.assertIn("--stage-coverage-path", argv)
        self.assertIn("coverage.json", argv)

    def test_latest_stage_coverage_path_selects_newest_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager_root = Path(tmp) / "manager"
            coverage_root = manager_root / "storage" / "runtime" / "stage_coverage"
            coverage_root.mkdir(parents=True)
            older = coverage_root / "older.json"
            newer = coverage_root / "newer.json"
            older.write_text("{}", encoding="utf-8")
            newer.write_text("{}", encoding="utf-8")
            os.utime(older, (1_700_000_000, 1_700_000_000))
            os.utime(newer, (1_700_000_100, 1_700_000_100))

            self.assertEqual(latest_stage_coverage_path(trading_manager_root=manager_root), newer)

    def test_public_refresh_batch_degrades_when_manager_producer_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            missing_manager = Path(tmp) / "missing-manager"

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/dashboard/refresh_public_dashboard_read_models.py",
                    "--storage-root",
                    str(storage_root),
                    "--trading-manager-root",
                    str(missing_manager),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "PYTHONPATH": "src"},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(completed.stdout)
            self.assertEqual(receipt["status"], "degraded")
            by_contract = {row["refreshed_contract_type"]: row for row in receipt["results"]}
            self.assertEqual(by_contract["current_system_status_summary"]["status"], "succeeded")
            self.assertEqual(by_contract[HISTORICAL_TASK_PROGRESS_CONTRACT]["status"], "failed")
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/current_system_status_summary/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
