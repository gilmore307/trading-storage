from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.storage_maintenance import (
    detect_completed_model_worker_folds,
    run_storage_maintenance,
    write_storage_maintenance_summary,
)


class StorageMaintenanceTests(unittest.TestCase):
    def test_maintenance_summary_preserves_side_effect_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            summary = run_storage_maintenance(root=root, generated_at_utc="2026-05-19T12:00:00Z")

        self.assertEqual(summary.contract_type, "storage_scheduled_maintenance_summary")
        self.assertTrue(summary.local_retention_enabled)
        self.assertFalse(summary.local_retention_apply)
        self.assertEqual(summary.fold_sql_backup_phase_status, "no_completed_fold_detected")
        self.assertEqual(summary.deletion_phase_status, "local_retention_only")
        self.assertFalse(summary.provider_calls_performed)
        self.assertFalse(summary.model_activation_performed)
        self.assertFalse(summary.broker_execution_performed)
        self.assertFalse(summary.account_mutation_performed)

    def test_maintenance_summary_writes_output_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            summary = run_storage_maintenance(root=root, generated_at_utc="2026-05-19T12:00:00Z")
            write_storage_maintenance_summary(summary, output_path=Path("storage/lifecycle/maintenance/summary.json"), root=root)
            payload = json.loads((root / "storage" / "lifecycle" / "maintenance" / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["contract_type"], "storage_scheduled_maintenance_summary")
        self.assertEqual(payload["generated_at_utc"], "2026-05-19T12:00:00Z")

    def test_detects_completed_manager_fold_state_without_manager_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            manager_root = Path(raw_tmp) / "trading-manager"
            runtime = manager_root / "storage" / "runtime"
            runtime.mkdir(parents=True)
            stages = [
                {
                    "stage_id": f"layer_{layer:02d}.{stage_type}",
                    "layer": layer,
                    "stage_type": stage_type,
                    "status": "succeeded",
                }
                for layer in range(1, 10)
                for stage_type in ("model_generation", "model_evaluation", "promotion_review", "maintenance")
            ]
            (runtime / "model_training_fold_state_2016-01_2016-06.json").write_text(
                json.dumps({"start_month": "2016-01", "end_month": "2016-06", "stages": stages}),
                encoding="utf-8",
            )

            candidates = detect_completed_model_worker_folds(manager_root=manager_root)
            summary = run_storage_maintenance(
                root=Path(raw_tmp) / "trading-storage",
                manager_root=manager_root,
                generated_at_utc="2026-05-19T12:00:00Z",
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["fold_id"], "fold_2016-01_2016-06")
        self.assertEqual(candidates[0]["backup_mode"], "logical_pg_dump_custom")
        self.assertIn("pg_dump", candidates[0]["backup_command_template"])
        self.assertEqual(summary.fold_sql_backup_phase_status, "ready_for_storage_backup")
        self.assertEqual(summary.completed_fold_ids, ("fold_2016-01_2016-06",))


if __name__ == "__main__":
    unittest.main()
