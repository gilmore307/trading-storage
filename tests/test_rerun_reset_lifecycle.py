from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.rerun_reset_lifecycle import (
    build_rerun_reset_lifecycle_plan,
    execute_rerun_reset_lifecycle,
)


def _write(path: Path, payload: str = "{}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return path


def _fixture_plan(root: Path) -> dict[str, object]:
    stage_key = "model_04_unified_decision__model_generation__train"
    candidate_model_ref = "storage://trading-manager/model_group/aapl/2016-01_2017-06"
    scope = {
        "scope_type": "model_group_fold",
        "fold_id": "fold_2016-01_2017-06",
        "state_path": str(root / "storage/02_control_plane/runtime/model_training_fold_state_aapl_2016-01_2017-06.json"),
        "start_month": "2016-01",
        "end_month": "2017-06",
        "target_symbols": ["AAPL"],
        "cutpoint": {
            "layer_id": 4,
            "stage": "model_generation",
            "cutpoint_stage_id": "model_04_unified_decision.model_generation.train",
        },
        "stage_keys": [stage_key],
        "candidate_model_refs": [candidate_model_ref],
    }
    explicit_ref = "storage://03_model_artifacts/runtime/aapl/generated/output.json"
    return {
        "contract_type": "model_group_rerun_plan",
        "plan_id": "mgr_rerun_plan_test",
        "rerun_id": "model_group_rerun_test",
        "reason": "test reset",
        "reset_scope": scope,
        "delete_set": [
            {
                "artifact_class": "model_artifact",
                "ref": explicit_ref,
                "delete_reason": "test reset",
                "requires_storage_lifecycle_review": False,
            }
        ],
        "generated_class_selectors": [
            {
                "selector_id": "downstream_stage_receipts",
                "root_class": "stage_receipts",
                "artifact_class": "runtime_evidence",
                "root_path": str(root / "storage/02_control_plane/runtime/model_training_stage_receipts"),
                "action": "delete",
                "final_handling_method": "delete",
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_stage_logs",
                "root_class": "stage_logs",
                "artifact_class": "runtime_evidence",
                "root_path": str(root / "storage/02_control_plane/runtime/model_training_stage_logs"),
                "action": "delete",
                "final_handling_method": "delete",
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_task_progress_sidecars",
                "root_class": "task_progress_sidecars",
                "artifact_class": "runtime_evidence",
                "root_path": str(root / "storage/02_control_plane/runtime/task_progress"),
                "action": "delete",
                "final_handling_method": "delete",
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_provider_task_sidecars",
                "root_class": "provider_task_sidecars",
                "artifact_class": "runtime_evidence",
                "root_path": str(root / "storage/02_control_plane/runtime/provider_task_keys"),
                "action": "blocked_pending_explicit_task_key_status",
                "final_handling_method": "not_applicable",
                "scope": scope,
                "reason": "status required",
            },
            {
                "selector_id": "downstream_explicit_artifact_refs",
                "root_class": "explicit_artifact_refs",
                "artifact_class": "generated_artifact",
                "root_path": str(root / "storage"),
                "action": "delete",
                "final_handling_method": "delete",
                "candidate_refs": [explicit_ref, "storage://03_model_artifacts/runtime/promoted/aapl/model.pkl"],
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_model_artifacts",
                "root_class": "model_artifacts",
                "artifact_class": "model_artifact",
                "root_path": str(root / "storage/03_model_artifacts/runtime"),
                "action": "delete_if_scope_matched_and_unpromoted",
                "final_handling_method": "delete",
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_replay_evaluation_settlement_promotion",
                "root_class": "replay_datasets",
                "artifact_class": "replay_artifact",
                "root_path": str(root / "storage/05_replay_datasets/promotion_replay_candidate_policy"),
                "action": "delete_if_scope_matched",
                "final_handling_method": "delete",
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_dashboard_read_models",
                "root_class": "dashboard_cache",
                "artifact_class": "derived_read_model",
                "root_path": str(root / "storage/06_dashboard_cache"),
                "action": "delete_snapshots_and_refresh_latest",
                "final_handling_method": "rolling_retention",
                "scope": scope,
                "reason": "test reset",
            },
            {
                "selector_id": "downstream_sql_rows",
                "root_class": "sql_rows",
                "artifact_class": "derived_or_generated_sql_rows",
                "root_path": "sql://trading-data/trading-model/trading-manager",
                "action": "blocked_pending_sql_executor",
                "final_handling_method": "not_applicable",
                "scope": scope,
                "reason": "sql executor required",
            },
        ],
        "protected_class_selectors": [
            {
                "selector_id": "protected_trading_economics_source",
                "root_class": "protected_source_data",
                "artifact_class": "source_evidence",
                "root_path": str(root / "storage/01_source_data/monthly_backfill/trading_economics_calendar_web"),
                "action": "retain",
                "reason": "protected source",
            }
        ],
    }


class RerunResetLifecycleTests(unittest.TestCase):
    def test_dry_run_classifies_every_reset_file_class_without_mutation(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            stage_key = "model_04_unified_decision__model_generation__train"
            receipt_dir = root / "storage/02_control_plane/runtime/model_training_stage_receipts" / stage_key
            log_dir = root / "storage/02_control_plane/runtime/model_training_stage_logs" / stage_key
            progress = root / "storage/02_control_plane/runtime/task_progress" / f"{stage_key}.json"
            provider_key = root / "storage/02_control_plane/runtime/provider_task_keys" / stage_key / "task_key.json"
            explicit_artifact = root / "storage/03_model_artifacts/runtime/aapl/generated/output.json"
            model_run = root / "storage/03_model_artifacts/runtime/aapl/model_run_1/metadata.json"
            mixed_model_run = root / "storage/03_model_artifacts/runtime/aapl/mixed_model_run/metadata.json"
            mixed_promoted_child = root / "storage/03_model_artifacts/runtime/aapl/mixed_model_run/promoted/model.pkl"
            promoted_model = root / "storage/03_model_artifacts/runtime/promoted/aapl/model.pkl"
            replay_run = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs/run1/replay_execution_receipt.json"
            promotion_run = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/promotion_review_runs/run2/promotion_eligibility_decision.json"
            snapshot = root / "storage/06_dashboard_cache/read_models/model_readiness_summary/snapshots/old.json"
            latest = root / "storage/06_dashboard_cache/read_models/model_readiness_summary.json"
            protected_source = root / "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/2016-01/source.json"
            protected_reset = root / "storage/02_control_plane/runtime/model_group_rerun_resets/model_group_rerun_test/receipt.json"

            _write(receipt_dir / "receipt.json", json.dumps({"target": "AAPL", "start_month": "2016-01", "end_month": "2017-06"}))
            _write(log_dir / "stdout.log", "AAPL 2016-01 2017-06\n")
            _write(progress, json.dumps({"target": "AAPL", "start_month": "2016-01", "end_month": "2017-06"}))
            _write(provider_key)
            _write(explicit_artifact)
            _write(model_run, json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}))
            _write(mixed_model_run, json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}))
            _write(mixed_promoted_child)
            _write(promoted_model)
            _write(replay_run, json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}))
            _write(promotion_run, json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}))
            _write(snapshot)
            _write(latest)
            _write(protected_source)
            _write(protected_reset)

            plan = build_rerun_reset_lifecycle_plan(root=root, rerun_plan=_fixture_plan(root))

            self.assertTrue(receipt_dir.exists())
            self.assertTrue(log_dir.exists())
            self.assertTrue(progress.exists())
            self.assertTrue(explicit_artifact.exists())
            self.assertTrue(model_run.exists())
            self.assertTrue(mixed_model_run.exists())
            self.assertTrue(mixed_promoted_child.exists())
            self.assertTrue(promoted_model.exists())
            self.assertTrue(snapshot.exists())
            self.assertGreaterEqual(plan["summary"]["delete_candidate_count"], 6)
            self.assertGreaterEqual(plan["summary"]["refresh_required_count"], 1)
            blocked_classes = {row["file_class"] for row in plan["blocked"]}
            self.assertIn("provider_task_sidecars", blocked_classes)
            self.assertIn("sql_rows", blocked_classes)
            self.assertTrue(any(row["file_class"] == "explicit_artifact_refs" and row.get("action") == "retain" for row in plan["blocked"]))
            self.assertTrue(any(row["file_class"] == "model_artifacts" and row.get("action") == "retain" for row in plan["blocked"]))

    def test_apply_deletes_generated_files_preserves_protected_and_writes_receipts(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            stage_key = "model_04_unified_decision__model_generation__train"
            receipt_dir = root / "storage/02_control_plane/runtime/model_training_stage_receipts" / stage_key
            log_dir = root / "storage/02_control_plane/runtime/model_training_stage_logs" / stage_key
            progress = root / "storage/02_control_plane/runtime/task_progress" / f"{stage_key}.json"
            provider_key = root / "storage/02_control_plane/runtime/provider_task_keys" / stage_key / "task_key.json"
            explicit_artifact = root / "storage/03_model_artifacts/runtime/aapl/generated/output.json"
            model_run_dir = root / "storage/03_model_artifacts/runtime/aapl/model_run_1"
            mixed_model_run_dir = root / "storage/03_model_artifacts/runtime/aapl/mixed_model_run"
            promoted_model = root / "storage/03_model_artifacts/runtime/promoted/aapl/model.pkl"
            replay_run_dir = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs/run1"
            promotion_run_dir = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/promotion_review_runs/run2"
            snapshot = root / "storage/06_dashboard_cache/read_models/model_readiness_summary/snapshots/old.json"
            latest = root / "storage/06_dashboard_cache/read_models/model_readiness_summary.json"
            protected_source = root / "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/2016-01/source.json"
            protected_reset = root / "storage/02_control_plane/runtime/model_group_rerun_resets/model_group_rerun_test/receipt.json"

            receipt_file = _write(
                receipt_dir / "receipt.json",
                json.dumps({"target": "AAPL", "start_month": "2016-01", "end_month": "2017-06"}),
            )
            log_file = _write(log_dir / "stdout.log", "AAPL 2016-01 2017-06\n")
            _write(progress, json.dumps({"target": "AAPL", "start_month": "2016-01", "end_month": "2017-06"}))
            _write(provider_key)
            _write(explicit_artifact)
            _write(
                model_run_dir / "metadata.json",
                json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}),
            )
            _write(
                mixed_model_run_dir / "metadata.json",
                json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}),
            )
            _write(mixed_model_run_dir / "promoted" / "model.pkl")
            _write(promoted_model)
            _write(
                replay_run_dir / "replay_execution_receipt.json",
                json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}),
            )
            _write(
                promotion_run_dir / "promotion_eligibility_decision.json",
                json.dumps({"candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06"}),
            )
            _write(snapshot)
            _write(latest)
            _write(protected_source)
            _write(protected_reset)

            receipt = execute_rerun_reset_lifecycle(root=root, rerun_plan=_fixture_plan(root), apply=True, approval_ref="test")

            self.assertFalse(receipt_file.exists())
            self.assertFalse(log_file.exists())
            self.assertFalse(progress.exists())
            self.assertFalse(explicit_artifact.exists())
            self.assertFalse(model_run_dir.exists())
            self.assertTrue(mixed_model_run_dir.exists())
            self.assertFalse(replay_run_dir.exists())
            self.assertFalse(promotion_run_dir.exists())
            self.assertFalse(snapshot.exists())
            self.assertTrue(provider_key.exists())
            self.assertTrue(promoted_model.exists())
            self.assertTrue(latest.exists())
            self.assertTrue(protected_source.exists())
            self.assertTrue(protected_reset.exists())
            self.assertTrue(Path(receipt["receipt_path"]).exists())
            self.assertTrue(Path(receipt["tombstone_path"]).exists())
            self.assertTrue(receipt["mutation_performed"])
            self.assertTrue(receipt["requires_dashboard_refresh"])
            self.assertTrue(receipt["requires_sql_cleanup"])


if __name__ == "__main__":
    unittest.main()
