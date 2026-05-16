from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index
from trading_storage.lifecycle_execution_scaffold import (
    build_lifecycle_execution_scaffold,
    write_lifecycle_execution_scaffold,
)
from trading_storage.lifecycle_planner import load_policy_rules, plan_storage_lifecycle, write_storage_lifecycle_plan
from trading_storage.quarantine_recheck import load_storage_lifecycle_plan_json


class LifecycleExecutionScaffoldTests(unittest.TestCase):
    def test_compression_candidate_gets_manifest_receipt_and_restore_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "pit_source_data" / "payload.csv"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("a,b\n1,2\n", encoding="utf-8")
            index = build_artifact_index(root=root)
            clear_record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "compress_and_retain",
                }
            )
            plan = plan_storage_lifecycle((clear_record,), generated_at="2026-05-16T00:00:00Z")

            scaffold = build_lifecycle_execution_scaffold(plan, generated_at="2026-05-16T00:01:00Z")

            self.assertEqual(scaffold.summary["compression_manifest_count"], 1)
            self.assertEqual(scaffold.summary["compression_receipt_count"], 1)
            self.assertEqual(scaffold.summary["restore_receipt_count"], 1)
            self.assertEqual(scaffold.summary["mutation_performed"], False)
            manifest = scaffold.compression_manifests[0]
            receipt = scaffold.compression_receipts[0]
            self.assertEqual(manifest.codec, "zstd")
            self.assertEqual(manifest.read_mode, "restore_required")
            self.assertEqual(manifest.original_checksum_sha256, clear_record.checksum_sha256)
            self.assertTrue(manifest.compressed_path.endswith("payload.csv.zst"))
            self.assertEqual(receipt.status, "planned_not_executed")
            self.assertFalse(receipt.mutation_performed)

    def test_archive_candidate_gets_archive_and_restore_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "sql_partition" / "partition.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "sql_partition_ref"}), encoding="utf-8")
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
            plan = plan_storage_lifecycle((clear_record,), rules=load_policy_rules(policy_path))

            scaffold = build_lifecycle_execution_scaffold(plan)

            self.assertEqual(scaffold.summary["archive_manifest_count"], 1)
            self.assertEqual(scaffold.summary["archive_receipt_count"], 1)
            self.assertEqual(scaffold.summary["restore_receipt_count"], 1)
            archive_manifest = scaffold.archive_manifests[0]
            archive_receipt = scaffold.archive_receipts[0]
            self.assertEqual(archive_manifest.export_command_class, "review_required_export")
            self.assertTrue(archive_manifest.archive_path.endswith(".dump.zst"))
            self.assertEqual(archive_receipt.detach_drop_quarantine_status, "not_started")
            self.assertFalse(archive_receipt.mutation_performed)

    def test_protected_records_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "example_payload"}), encoding="utf-8")
            plan = plan_storage_lifecycle(build_artifact_index(root=root))

            scaffold = build_lifecycle_execution_scaffold(plan)

            self.assertEqual(scaffold.summary["compression_manifest_count"], 0)
            self.assertEqual(scaffold.summary["skipped_record_count"], 1)
            self.assertEqual(scaffold.skipped_records[0]["skip_reason"], "protected_by_lifecycle_plan")

    def test_quarantine_candidates_do_not_get_delete_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "scratch" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "scratch_payload"}), encoding="utf-8")
            index = build_artifact_index(root=root)
            clear_record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "ttl_delete_allowed",
                }
            )
            plan = plan_storage_lifecycle((clear_record,))

            scaffold = build_lifecycle_execution_scaffold(plan)

            self.assertEqual(scaffold.summary["skipped_action_counts"], {"quarantine_candidate": 1})
            self.assertEqual(scaffold.summary["compression_receipt_count"], 0)
            self.assertEqual(scaffold.summary["archive_receipt_count"], 0)
            self.assertEqual(scaffold.summary["mutation_performed"], False)

    def test_lifecycle_plan_and_scaffold_outputs_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "pit_source_data" / "payload.csv"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("a,b\n1,2\n", encoding="utf-8")
            index = build_artifact_index(root=root)
            clear_record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "compress_and_retain",
                }
            )
            plan = plan_storage_lifecycle((clear_record,), generated_at="2026-05-16T00:00:00Z")
            write_storage_lifecycle_plan(plan, output_path=root / "storage" / "lifecycle_plan" / "plan.json")
            loaded_plan = load_storage_lifecycle_plan_json(root / "storage" / "lifecycle_plan" / "plan.json")

            scaffold = build_lifecycle_execution_scaffold(loaded_plan)
            write_lifecycle_execution_scaffold(
                scaffold,
                output_path=root / "storage" / "lifecycle_execution" / "scaffold.json",
                summary_path=root / "storage" / "lifecycle_execution" / "summary.json",
            )

            payload = json.loads((root / "storage" / "lifecycle_execution" / "scaffold.json").read_text(encoding="utf-8"))
            summary = json.loads((root / "storage" / "lifecycle_execution" / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["contract_type"], "storage_lifecycle_execution_scaffold_v1")
            self.assertEqual(payload["source_lifecycle_plan_generated_at"], "2026-05-16T00:00:00Z")
            self.assertEqual(summary["contract_type"], "storage_lifecycle_execution_scaffold_summary_v1")
            self.assertEqual(summary["executor_mode"], "dry_run_scaffold_only")


if __name__ == "__main__":
    unittest.main()
