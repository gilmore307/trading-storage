from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index
from trading_storage.lifecycle_planner import load_policy_rules, plan_storage_lifecycle
from trading_storage.sql_archive import (
    execute_sql_archive,
    verify_sql_archive_restore,
    write_sql_archive_result,
)


class SqlArchiveExecutorTests(unittest.TestCase):
    def _archive_plan(self, root: Path):
        artifact = root / "storage" / "02_control_plane" / "artifacts" / "sql_partition" / "partition.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps({"contract_type": "sql_partition_ref", "rows": 2}), encoding="utf-8")
        index = build_artifact_index(root=root)
        clear_record = index.records[0].__class__(
            **{
                **index.records[0].to_dict(),
                "protected_reason_codes": (),
                "retention_class": "sql_archive_allowed",
            }
        )
        policy_path = root / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "policy_id": "sql_archive_policy",
                            "rule_id": "archive_closed_partition",
                            "selector": {"retention_class": "sql_archive_allowed"},
                            "action": "archive_candidate",
                            "require_protected_set_clear": True,
                            "reason": "closed partition archive candidate",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return plan_storage_lifecycle((clear_record,), rules=load_policy_rules(policy_path))

    def test_dry_run_plans_archive_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._archive_plan(root)

            result = execute_sql_archive(plan, root=root, generated_at="2026-05-17T00:00:00Z")

            self.assertFalse(result.summary["mutation_performed"])
            self.assertFalse(result.summary["sql_mutation_performed"])
            self.assertEqual(result.summary["status_counts"], {"planned_not_executed": 1})
            self.assertEqual(result.manifests[0].archive_format, "gzip_file_backed_reviewed_export")
            self.assertEqual(result.receipts[0].detach_drop_quarantine_status, "not_started")

    def test_apply_writes_archive_copy_and_restore_verifier_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._archive_plan(root)

            result = execute_sql_archive(plan, root=root, apply=True, generated_at="2026-05-17T00:00:00Z")

            self.assertEqual(result.summary["status_counts"], {"succeeded": 1})
            self.assertTrue(result.summary["mutation_performed"])
            self.assertFalse(result.summary["sql_mutation_performed"])
            self.assertFalse(result.summary["source_delete_performed"])
            archive_path = root / result.manifests[0].archive_path
            self.assertTrue(archive_path.exists())
            self.assertEqual(result.restore_receipts[0].checksum_status, "passed")

            write_sql_archive_result(
                result,
                output_path=root / "storage" / "lifecycle_execution" / "sql_archive_result.json",
                summary_path=root / "storage" / "lifecycle_execution" / "sql_archive_summary.json",
            )
            verification = verify_sql_archive_restore(result, root=root, generated_at="2026-05-17T00:01:00Z")

            self.assertEqual(verification.summary["status_counts"], {"succeeded": 1})
            self.assertFalse(verification.summary["mutation_performed"])
            self.assertEqual(verification.receipts[0].checksum_status, "passed")


if __name__ == "__main__":
    unittest.main()
