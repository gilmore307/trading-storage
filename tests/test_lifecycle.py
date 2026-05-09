from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from trading_storage.lifecycle import apply_retention_plan, plan_retention


class LifecycleTests(unittest.TestCase):
    def _touch_old(self, path: Path, *, age_days: int, content: str = "payload") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))

    def test_temporary_files_are_deleted_after_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / "tmp" / "scratch.json"
            self._touch_old(scratch, age_days=4)

            plan = plan_retention(root=root)
            self.assertEqual(plan.summary["delete"], 1)
            self.assertEqual(plan.items[0].path, "tmp/scratch.json")

            applied = apply_retention_plan(plan)
            self.assertFalse(scratch.exists())
            self.assertFalse(applied.dry_run)

    def test_logs_are_archived_before_active_copy_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "logs" / "daily.log"
            self._touch_old(log, age_days=15, content="important diagnostic")

            plan = plan_retention(root=root)
            self.assertEqual(plan.summary["archive"], 1)
            item = plan.items[0]
            self.assertEqual(item.path, "logs/daily.log")
            self.assertEqual(item.archive_path, "storage/archive/logs/daily.log")

            apply_retention_plan(plan)
            self.assertFalse(log.exists())
            self.assertEqual((root / "storage/archive/logs/daily.log").read_text(encoding="utf-8"), "important diagnostic")

    def test_storage_artifacts_are_reported_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "component_completion_receipt" / "receipt.json"
            self._touch_old(artifact, age_days=365)

            plan = plan_retention(root=root)
            self.assertEqual(plan.summary["retain"], 1)
            self.assertEqual(plan.items[0].path, "storage/artifacts/component_completion_receipt/receipt.json")
            self.assertTrue(artifact.exists())

    def test_python_caches_are_disposable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_file = root / "src" / "pkg" / "__pycache__" / "module.cpython-312.pyc"
            self._touch_old(cache_file, age_days=0)

            plan = plan_retention(root=root)
            self.assertEqual(plan.summary["delete"], 1)
            self.assertEqual(plan.items[0].rule, "python_caches")

            apply_retention_plan(plan)
            self.assertFalse(cache_file.exists())
            self.assertFalse(cache_file.parent.exists())

    def test_archive_root_must_stay_under_repository_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                plan_retention(root=Path(tmp), archive_root=Path("/tmp/outside-storage-archive"))

    def test_cli_json_shape_is_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / "tmp" / "scratch.json"
            self._touch_old(scratch, age_days=4)
            data = json.loads(plan_retention(root=root).to_json())

            self.assertEqual(data["summary"]["delete"], 1)
            self.assertEqual(data["items"][0]["action"], "delete")


if __name__ == "__main__":
    unittest.main()
