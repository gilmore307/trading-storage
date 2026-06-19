from __future__ import annotations

import json
import tempfile
import unittest
import gzip
from pathlib import Path

from trading_storage.storage_maintenance import (
    detect_completed_model_worker_folds,
    detect_fold_scoped_source_cleanup_candidates,
    detect_lifecycle_gap_findings,
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
        self.assertEqual(summary.lifecycle_gap_audit_summary["finding_count"], 0)
        self.assertEqual(summary.lifecycle_gap_findings, ())
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
        self.assertEqual(payload["lifecycle_gap_audit_summary"]["contract_type"], "storage_lifecycle_gap_audit_summary")

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
            source_file = fold_folder / "targets" / "AAPL" / "model_02_source.json"
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

    def test_lifecycle_gap_audit_reports_known_unbounded_classes_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            replay_run = (
                root
                / "storage"
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "replay_execution_runs"
                / "model_group_replay_20260613T111021Z"
            )
            for index in range(4):
                run = replay_run.parent / f"model_group_replay_2026061{index}T111021Z"
                run.mkdir(parents=True)
                (run / "decision_rows.jsonl").write_text("row\n", encoding="utf-8")
                (run / "replay_execution_receipt.json").write_text(
                    json.dumps({"validation_status": "passed", "replay_execution_run_id": run.name}),
                    encoding="utf-8",
                )
            task_key = (
                root
                / "storage"
                / "02_control_plane"
                / "runtime"
                / "model_05_option_expression"
                / "option_chain_state_source"
                / "2025-01"
                / "AAPL"
                / "task_key.json"
            )
            task_key.parent.mkdir(parents=True)
            task_key.write_text("{}", encoding="utf-8")

            findings = detect_lifecycle_gap_findings(root=root)
            summary = run_storage_maintenance(
                root=root,
                include_local_retention=False,
                generated_at_utc="2026-05-19T12:00:00Z",
            )

        by_ref = {finding["artifact_ref"]: finding for finding in findings}
        replay_ref = "storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs"
        task_key_ref = "storage/02_control_plane/runtime/model_05_option_expression"
        self.assertEqual(by_ref[replay_ref]["action"], "compact")
        self.assertEqual(by_ref[replay_ref]["final_handling_method"], "delete")
        self.assertEqual(by_ref[replay_ref]["file_count"], 1)
        self.assertFalse(by_ref[replay_ref]["mutation_performed"])
        self.assertEqual(by_ref[task_key_ref]["issue"], "per_request_task_key_sprawl")
        self.assertEqual(by_ref[task_key_ref]["file_count"], 1)
        self.assertEqual(summary.lifecycle_gap_audit_summary["finding_count"], 2)
        self.assertFalse(summary.lifecycle_gap_audit_summary["mutation_performed"])

    def test_lifecycle_gap_actions_apply_only_explicit_compact_safe_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            replay_old = (
                root
                / "storage"
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "replay_execution_runs"
                / "replay_20260610T000000Z"
            )
            replay_new = replay_old.parent / "replay_20260613T000000Z"
            for run in (replay_old, replay_new):
                run.mkdir(parents=True)
                (run / "replay_execution_receipt.json").write_text(
                    json.dumps({"validation_status": "passed", "replay_execution_run_id": run.name}),
                    encoding="utf-8",
                )
                (run / "decision_rows.jsonl").write_text("row\n", encoding="utf-8")

            triage = (
                root
                / "storage"
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "post_replay_failure_triage_runs"
                / "triage_20260613T000000Z"
            )
            triage.mkdir(parents=True)
            (triage / "failure_triage_rows.jsonl").write_text("triage\n", encoding="utf-8")

            refresh_old = (
                root
                / "storage"
                / "01_source_data"
                / "monthly_backfill"
                / "trading_economics_calendar_web"
                / "_manifests"
                / "recent_refresh_runs"
                / "calendar_20260610T000000Z"
            )
            refresh_new = refresh_old.parent / "calendar_20260613T000000Z"
            for run in (refresh_old, refresh_new):
                run.mkdir(parents=True)
                (run / "completion_receipt.json").write_text("{}", encoding="utf-8")

            te_month_old = (
                root
                / "storage"
                / "01_source_data"
                / "monthly_backfill"
                / "trading_economics_calendar_web"
                / "2026-06"
                / "runs"
                / "calendar_maintenance_20260610T000000Z_te"
            )
            te_month_new = te_month_old.parent / "calendar_maintenance_20260613T000000Z_te"
            for run in (te_month_old, te_month_new):
                (run / "saved").mkdir(parents=True)
                (run / "cleaned").mkdir(parents=True)
                (run / "saved" / "trading_economics_calendar_event.csv").write_text("event_time,event\n", encoding="utf-8")
                (run / "cleaned" / "trading_economics_calendar_event.jsonl").write_text('{"event":"NFP"}\n', encoding="utf-8")
                (run / "request_manifest.json").write_text("{}", encoding="utf-8")
                (run / "completion_receipt.json").write_text(
                    json.dumps({"status": "succeeded", "row_counts": {"trading_economics_calendar_event": 1}}),
                    encoding="utf-8",
                )

            realtime_old = root / "storage" / "04_execution_artifacts" / "runtime" / "realtime_monitor" / "20260610T000000Z"
            realtime_new = realtime_old.parent / "20260613T000000Z"
            for run in (realtime_old, realtime_new):
                run.mkdir(parents=True)
                (run / "loop_receipt.json").write_text(json.dumps({"loop_status": "completed", "failed_cycle_indexes": []}), encoding="utf-8")

            summary = run_storage_maintenance(
                root=root,
                include_local_retention=False,
                apply_lifecycle_gap_actions=True,
                retain_recent_replay_runs=1,
                retain_recent_te_refresh_runs=1,
                retain_recent_te_monthly_runs=1,
                retain_recent_realtime_loops=1,
                generated_at_utc="2026-06-13T12:00:00Z",
            )

            self.assertTrue(summary.lifecycle_gap_action_summary["mutation_performed"])
            self.assertFalse((replay_old / "decision_rows.jsonl").exists())
            self.assertTrue((replay_new / "decision_rows.jsonl").exists())
            compressed = triage / "failure_triage_rows.jsonl.gz"
            self.assertTrue(compressed.exists())
            self.assertFalse((triage / "failure_triage_rows.jsonl").exists())
            with gzip.open(compressed, "rt", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "triage\n")
            self.assertFalse(refresh_old.exists())
            self.assertTrue(refresh_new.exists())
            self.assertTrue((te_month_old / "saved" / "trading_economics_calendar_event.csv").exists())
            self.assertTrue((te_month_old / "cleaned" / "trading_economics_calendar_event.jsonl").exists())
            self.assertFalse((te_month_old / "completion_receipt.json").exists())
            self.assertFalse((te_month_old / "request_manifest.json").exists())
            self.assertTrue((te_month_new / "completion_receipt.json").exists())
            self.assertFalse(realtime_old.exists())
            self.assertTrue(realtime_new.exists())
            compact_root = root / "storage" / "90_lifecycle" / "maintenance" / "compact_contracts"
            self.assertTrue((compact_root / "replay_execution_runs_compact_manifest.json").exists())
            self.assertTrue((compact_root / "te_monthly_source_provenance_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
