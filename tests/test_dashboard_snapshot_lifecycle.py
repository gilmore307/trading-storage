from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trading_storage.dashboard_snapshot_lifecycle import (
    build_dashboard_snapshot_lifecycle_plan,
    compact_dashboard_read_model_index,
    write_dashboard_snapshot_lifecycle_plan,
)

NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)


def _write_snapshot(storage_root: Path, contract: str, stamp: str, size: int = 10) -> Path:
    parsed = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    path = (
        storage_root
        / "06_dashboard_cache"
        / "read_models"
        / contract
        / "snapshots"
        / parsed.strftime("%Y")
        / parsed.strftime("%m")
        / parsed.strftime("%d")
        / f"{stamp}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * size, encoding="utf-8")
    return path


def _write_issue_snapshot(storage_root: Path, contract: str, stamp: str) -> Path:
    path = _write_snapshot(storage_root, contract, stamp)
    path.write_text(
        json.dumps({"contract_type": contract, "issue_refs": [{"issue_type": "test_alert", "status": "open"}]}),
        encoding="utf-8",
    )
    return path


class DashboardSnapshotLifecycleTests(unittest.TestCase):
    def test_default_policy_keeps_only_recent_few_per_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            for hour in range(12):
                _write_snapshot(storage_root, "current_system_status_summary", f"20260516T{hour:02d}0000Z")

            plan = build_dashboard_snapshot_lifecycle_plan(
                storage_root=storage_root,
                apply=False,
                now=NOW,
                generated_at="2026-05-16T12:00:00Z",
            )

            self.assertEqual(plan.keep_latest_per_contract, 10)
            self.assertEqual(plan.max_age_hours, 0)
            self.assertEqual(plan.summary["action_counts"], {"delete_candidate": 2, "retain_recent_snapshot": 10})
            self.assertFalse(plan.summary["mutation_performed"])

    def test_dry_run_marks_old_snapshots_without_deleting_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            old = _write_snapshot(storage_root, "historical_task_progress_summary", "20260514T000000Z")
            recent = _write_snapshot(storage_root, "historical_task_progress_summary", "20260516T110000Z")
            latest = storage_root / "06_dashboard_cache" / "read_models" / "historical_task_progress_summary" / "latest.json"
            latest.write_text("latest", encoding="utf-8")

            plan = build_dashboard_snapshot_lifecycle_plan(
                storage_root=storage_root,
                max_age_hours=24,
                keep_latest_per_contract=1,
                apply=False,
                now=NOW,
                generated_at="2026-05-16T12:00:00Z",
            )

            self.assertTrue(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(latest.exists())
            self.assertEqual(plan.summary["action_counts"], {"delete_candidate": 1, "retain_recent_snapshot": 1})
            self.assertFalse(plan.summary["mutation_performed"])
            self.assertFalse(plan.summary["latest_json_deleted"])

    def test_apply_deletes_only_old_snapshot_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            old = _write_snapshot(storage_root, "historical_task_progress_summary", "20260514T000000Z")
            recent = _write_snapshot(storage_root, "historical_task_progress_summary", "20260516T110000Z")
            latest = storage_root / "06_dashboard_cache" / "read_models" / "historical_task_progress_summary" / "latest.json"
            latest.write_text("latest", encoding="utf-8")

            plan = build_dashboard_snapshot_lifecycle_plan(
                storage_root=storage_root,
                max_age_hours=24,
                keep_latest_per_contract=1,
                apply=True,
                now=NOW,
                approval_ref="accepted_storage_lifecycle_decision_ref:test",
            )

            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(latest.exists())
            self.assertEqual(plan.summary["action_counts"], {"deleted": 1, "retain_recent_snapshot": 1})
            self.assertTrue(plan.summary["mutation_performed"])
            self.assertFalse(plan.summary["layer_01_02_data_deleted"])
            self.assertFalse(plan.summary["sql_mutation_performed"])

    def test_unresolved_issue_snapshots_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            old = _write_issue_snapshot(storage_root, "current_system_status_summary", "20260514T000000Z")
            recent = _write_snapshot(storage_root, "current_system_status_summary", "20260516T110000Z")

            plan = build_dashboard_snapshot_lifecycle_plan(
                storage_root=storage_root,
                max_age_hours=24,
                keep_latest_per_contract=1,
                apply=True,
                now=NOW,
                approval_ref="accepted_storage_lifecycle_decision_ref:test",
            )

            self.assertTrue(old.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(
                plan.summary["action_counts"],
                {"retain_recent_snapshot": 1, "retain_unresolved_issue_snapshot": 1},
            )

    def test_write_plan_outputs_json_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            _write_snapshot(storage_root, "current_system_status_summary", "20260516T110000Z")
            plan = build_dashboard_snapshot_lifecycle_plan(storage_root=storage_root, now=NOW)

            write_dashboard_snapshot_lifecycle_plan(
                plan,
                output_path=Path("storage/06_dashboard_cache/lifecycle/plan.json"),
                summary_path=Path("storage/06_dashboard_cache/lifecycle/summary.json"),
            )

            payload = json.loads((storage_root / "06_dashboard_cache" / "lifecycle" / "plan.json").read_text(encoding="utf-8"))
            summary = json.loads((storage_root / "06_dashboard_cache" / "lifecycle" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["contract_type"], "dashboard_snapshot_prune_plan")
            self.assertEqual(summary["contract_type"], "dashboard_snapshot_prune_summary")

    def test_apply_requires_approval_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            _write_snapshot(storage_root, "historical_task_progress_summary", "20260514T000000Z")

            with self.assertRaisesRegex(ValueError, "approval_ref is required"):
                build_dashboard_snapshot_lifecycle_plan(
                    storage_root=storage_root,
                    max_age_hours=24,
                    keep_latest_per_contract=1,
                    apply=True,
                    now=NOW,
                )

    def test_index_compaction_drops_rows_for_deleted_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            kept = _write_snapshot(storage_root, "current_system_status_summary", "20260516T110000Z")
            removed = _write_snapshot(storage_root, "current_system_status_summary", "20260514T000000Z")
            index = storage_root / "06_dashboard_cache" / "index" / "dashboard_read_model_index.jsonl"
            index.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "contract_type": "current_system_status_summary",
                    "snapshot_uri": "storage://trading-storage/" + str(kept.relative_to(storage_root)).replace("\\", "/"),
                },
                {
                    "contract_type": "current_system_status_summary",
                    "snapshot_uri": "storage://trading-storage/" + str(removed.relative_to(storage_root)).replace("\\", "/"),
                },
            ]
            index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
            removed.unlink()

            summary = compact_dashboard_read_model_index(storage_root=storage_root)

            self.assertEqual(summary["input_rows"], 2)
            self.assertEqual(summary["retained_rows"], 1)
            self.assertEqual(summary["dropped_rows"], 1)
            compacted_rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(compacted_rows, [rows[0]])


if __name__ == "__main__":
    unittest.main()
