from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index
from trading_storage.lifecycle_planner import plan_storage_lifecycle, write_storage_lifecycle_plan
from trading_storage.quarantine_recheck import load_storage_lifecycle_plan_json
from trading_storage.single_file_compression import (
    execute_single_file_compression,
    write_single_file_compression_result,
)


class SingleFileCompressionTests(unittest.TestCase):
    def _compression_plan(self, root: Path):
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
        return plan_storage_lifecycle((clear_record,), generated_at="2026-05-16T00:00:00Z"), artifact

    def test_dry_run_does_not_write_compressed_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, artifact = self._compression_plan(root)

            result = execute_single_file_compression(plan, root=root, apply=False, generated_at="2026-05-16T00:01:00Z")

            self.assertEqual(result.summary["status_counts"], {"planned_not_executed": 1})
            self.assertFalse(result.summary["mutation_performed"])
            self.assertTrue(artifact.exists())
            self.assertFalse((root / result.manifests[0].compressed_path).exists())
            self.assertEqual(result.receipts[0].restore_smoke_status, "not_performed_dry_run")
            self.assertFalse(result.receipts[0].delete_original_performed)

    @unittest.skipIf(shutil.which("zstd") is None, "zstd command not available")
    def test_apply_writes_compressed_copy_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, artifact = self._compression_plan(root)

            result = execute_single_file_compression(plan, root=root, apply=True, generated_at="2026-05-16T00:01:00Z")

            compressed_path = root / result.manifests[0].compressed_path
            self.assertTrue(compressed_path.exists())
            self.assertTrue(artifact.exists())
            self.assertEqual(result.summary["status_counts"], {"succeeded": 1})
            self.assertTrue(result.summary["mutation_performed"])
            self.assertEqual(result.receipts[0].restore_smoke_status, "match")
            self.assertEqual(result.restore_receipts[0].checksum_status, "match")
            self.assertFalse(result.receipts[0].delete_original_performed)
            self.assertFalse(result.receipts[0].artifact_index_updated)
            self.assertFalse(result.receipts[0].sql_mutation_performed)

    def test_protected_records_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "example_payload"}), encoding="utf-8")
            plan = plan_storage_lifecycle(build_artifact_index(root=root))

            result = execute_single_file_compression(plan, root=root, apply=True)

            self.assertEqual(result.summary["skipped_reason_counts"], {"protected_by_lifecycle_plan": 1})
            self.assertEqual(result.summary["receipt_count"], 0)
            self.assertFalse(result.summary["mutation_performed"])

    def test_quarantine_candidates_are_not_compressed(self):
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

            result = execute_single_file_compression(plan, root=root, apply=True)

            self.assertEqual(result.summary["skipped_reason_counts"], {"not_compress_candidate": 1})
            self.assertFalse(result.summary["delete_original_performed"])

    @unittest.skipIf(shutil.which("zstd") is None, "zstd command not available")
    def test_apply_refuses_existing_compressed_output_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, _artifact = self._compression_plan(root)
            first = execute_single_file_compression(plan, root=root, apply=True)
            self.assertEqual(first.summary["status_counts"], {"succeeded": 1})

            second = execute_single_file_compression(plan, root=root, apply=True)

            self.assertEqual(second.summary["skipped_reason_counts"], {"compressed_path_exists": 1})
            self.assertEqual(second.summary["receipt_count"], 0)

    def test_plan_and_result_outputs_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, _artifact = self._compression_plan(root)
            write_storage_lifecycle_plan(plan, output_path=root / "storage" / "lifecycle_plan" / "plan.json")
            loaded_plan = load_storage_lifecycle_plan_json(root / "storage" / "lifecycle_plan" / "plan.json")

            result = execute_single_file_compression(loaded_plan, root=root, apply=False)
            write_single_file_compression_result(
                result,
                output_path=root / "storage" / "lifecycle_execution" / "compression.json",
                summary_path=root / "storage" / "lifecycle_execution" / "compression_summary.json",
            )

            payload = json.loads((root / "storage" / "lifecycle_execution" / "compression.json").read_text(encoding="utf-8"))
            summary = json.loads((root / "storage" / "lifecycle_execution" / "compression_summary.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["contract_type"], "storage_single_file_compression_result")
            self.assertEqual(payload["source_lifecycle_plan_generated_at"], "2026-05-16T00:00:00Z")
            self.assertEqual(summary["contract_type"], "storage_single_file_compression_summary")

    def test_compressed_output_paths_use_full_artifact_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "storage" / "artifacts" / "pit_source_data" / "a" / "same.csv"
            second = root / "storage" / "artifacts" / "pit_source_data" / "b" / "same.csv"
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            first.write_text("a,b\n1,2\n", encoding="utf-8")
            second.write_text("a,b\n1,2\n", encoding="utf-8")
            index = build_artifact_index(root=root)
            clear_records = tuple(
                record.__class__(
                    **{
                        **record.to_dict(),
                        "artifact_id": "same",
                        "protected_reason_codes": (),
                        "retention_class": "compress_and_retain",
                    }
                )
                for record in index.records
            )
            plan = plan_storage_lifecycle(clear_records)

            result = execute_single_file_compression(plan, root=root, apply=False)

            compressed_paths = {manifest.compressed_path for manifest in result.manifests}
            self.assertEqual(len(compressed_paths), 2)
            self.assertTrue(all(path.endswith("same.csv.zst") for path in compressed_paths))


if __name__ == "__main__":
    unittest.main()
