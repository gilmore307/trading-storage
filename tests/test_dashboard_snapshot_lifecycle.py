from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trading_storage.dashboard_snapshot_lifecycle import (
    build_dashboard_snapshot_lifecycle_plan,
    write_dashboard_snapshot_lifecycle_plan,
)

NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)


def _write_snapshot(storage_root: Path, contract: str, stamp: str, size: int = 10) -> Path:
    parsed = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    path = (
        storage_root
        / "dashboard"
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


class DashboardSnapshotLifecycleTests(unittest.TestCase):
    def test_dry_run_marks_old_snapshots_without_deleting_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            old = _write_snapshot(storage_root, "historical_task_progress_summary", "20260514T000000Z")
            recent = _write_snapshot(storage_root, "historical_task_progress_summary", "20260516T110000Z")
            latest = storage_root / "dashboard" / "read_models" / "historical_task_progress_summary" / "latest.json"
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
            latest = storage_root / "dashboard" / "read_models" / "historical_task_progress_summary" / "latest.json"
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

    def test_write_plan_outputs_json_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            _write_snapshot(storage_root, "current_system_status_summary", "20260516T110000Z")
            plan = build_dashboard_snapshot_lifecycle_plan(storage_root=storage_root, now=NOW)

            write_dashboard_snapshot_lifecycle_plan(
                plan,
                output_path=Path("storage/dashboard/lifecycle/plan.json"),
                summary_path=Path("storage/dashboard/lifecycle/summary.json"),
            )

            payload = json.loads((storage_root / "dashboard" / "lifecycle" / "plan.json").read_text(encoding="utf-8"))
            summary = json.loads((storage_root / "dashboard" / "lifecycle" / "summary.json").read_text(encoding="utf-8"))
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


if __name__ == "__main__":
    unittest.main()
