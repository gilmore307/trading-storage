from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.storage_maintenance import (
    detect_completed_model_worker_folds,
    detect_fold_scoped_source_cleanup_candidates,
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
        self.assertEqual(summary.fold_source_cleanup_phase_status, "no_fold_scoped_source_cleanup_candidates")
        self.assertEqual(summary.deletion_phase_status, "local_retention_only")
        self.assertEqual(summary.storage_root_inventory_summary["root_count"], 7)
        self.assertEqual(
            summary.storage_root_inventory_summary["managed_root_ids"],
            [
                "01_source_data",
                "02_control_plane",
                "03_model_artifacts",
                "04_execution_artifacts",
                "05_replay_datasets",
                "06_dashboard_cache",
                "90_lifecycle",
            ],
        )
        self.assertFalse(summary.provider_calls_performed)
        self.assertFalse(summary.model_activation_performed)
        self.assertFalse(summary.broker_execution_performed)
        self.assertFalse(summary.account_mutation_performed)

    def test_maintenance_summary_writes_output_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            summary = run_storage_maintenance(root=root, generated_at_utc="2026-05-19T12:00:00Z")
            write_storage_maintenance_summary(summary, output_path=Path("storage/90_lifecycle/maintenance/summary.json"), root=root)
            payload = json.loads((root / "storage" / "90_lifecycle" / "maintenance" / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["contract_type"], "storage_scheduled_maintenance_summary")
        self.assertEqual(payload["generated_at_utc"], "2026-05-19T12:00:00Z")
        self.assertEqual(payload["storage_root_inventory_summary"]["root_count"], 7)

    def test_root_inventory_records_numbered_storage_roots(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            source_file = root / "storage" / "01_source_data" / "monthly_backfill" / "bars.json"
            execution_file = root / "storage" / "04_execution_artifacts" / "runtime" / "receipt.json"
            source_file.parent.mkdir(parents=True)
            execution_file.parent.mkdir(parents=True)
            source_file.write_text("source", encoding="utf-8")
            execution_file.write_text("execution", encoding="utf-8")

            summary = run_storage_maintenance(root=root, generated_at_utc="2026-05-19T12:00:00Z")
            by_id = {row["root_id"]: row for row in summary.storage_root_inventory}

        self.assertTrue(by_id["01_source_data"]["exists"])
        self.assertTrue(by_id["04_execution_artifacts"]["exists"])
        self.assertEqual(by_id["01_source_data"]["file_count"], 1)
        self.assertEqual(by_id["04_execution_artifacts"]["byte_count"], len("execution"))

    def test_skip_local_retention_keeps_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            (root / "storage" / "90_lifecycle").mkdir(parents=True)
            summary = run_storage_maintenance(
                root=root,
                include_local_retention=False,
                generated_at_utc="2026-05-19T12:00:00Z",
            )

        self.assertFalse(summary.local_retention_enabled)
        self.assertEqual(summary.deletion_phase_status, "local_retention_skipped")
        self.assertEqual(summary.storage_root_inventory_summary["root_count"], 7)

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
                for layer in range(1, 11)
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

    def test_detects_fold_scoped_source_cleanup_candidate_after_completed_fold(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "trading-storage"
            fold_folder = root / "storage" / "01_source_data" / "fold_scoped" / "fold_2016-01_2016-06"
            source_file = fold_folder / "targets" / "AAPL" / "layer_03_source.json"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("payload", encoding="utf-8")

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
                for layer in range(1, 11)
                for stage_type in ("model_generation", "model_evaluation", "promotion_review", "maintenance")
            ]
            (runtime / "model_training_fold_state_2016-01_2016-06.json").write_text(
                json.dumps({"start_month": "2016-01", "end_month": "2016-06", "stages": stages}),
                encoding="utf-8",
            )

            candidates = detect_fold_scoped_source_cleanup_candidates(
                root=root,
                completed_fold_ids=("fold_2016-01_2016-06",),
            )
            summary = run_storage_maintenance(
                root=root,
                manager_root=manager_root,
                generated_at_utc="2026-05-19T12:00:00Z",
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["contract_type"], "storage_fold_source_cleanup_candidate")
        self.assertEqual(candidates[0]["source_folder_path"], "storage/01_source_data/fold_scoped/fold_2016-01_2016-06")
        self.assertEqual(candidates[0]["file_count"], 1)
        self.assertFalse(candidates[0]["deletion_performed"])
        self.assertEqual(summary.fold_source_cleanup_candidate_count, 1)
        self.assertEqual(summary.fold_source_cleanup_phase_status, "ready_for_quarantine_review")


if __name__ == "__main__":
    unittest.main()
