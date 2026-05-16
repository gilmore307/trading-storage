from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index, write_artifact_index


class ArtifactIndexTests(unittest.TestCase):
    def test_indexes_storage_artifact_payload_conservatively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "storage" / "artifacts" / "component_completion_receipt" / "receipt-1.json"
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(
                json.dumps(
                    {
                        "contract_type": "component_completion_receipt_payload",
                        "producer_repo": "trading-data",
                        "workflow_id": "alpaca_bars",
                        "run_id": "run_1",
                        "schema_ref": "component_completion_receipt_payload",
                        "lineage_refs": ["source://alpaca/bars"],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root, generated_at="2026-05-16T00:00:00Z")

            self.assertEqual(index.summary["record_count"], 1)
            record = index.records[0]
            self.assertEqual(record.artifact_id, "receipt-1")
            self.assertEqual(record.artifact_kind, "component_completion_receipt_payload")
            self.assertEqual(record.producer_repo, "trading-data")
            self.assertEqual(record.producer_component, "alpaca_bars")
            self.assertEqual(record.producer_run_id, "run_1")
            self.assertEqual(record.storage_backend, "filesystem")
            self.assertEqual(record.content_format, "json")
            self.assertEqual(record.content_codec, "none")
            self.assertEqual(record.read_mode, "direct_readable")
            self.assertEqual(record.retention_class, "manual_review_required")
            self.assertEqual(record.protected_reason_codes, ("unknown_metadata",))
            self.assertEqual(record.lineage_refs, ("source://alpaca/bars",))

    def test_dashboard_read_model_payload_is_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "storage" / "dashboard" / "read_models" / "current_system_status_summary" / "latest.json"
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(
                json.dumps(
                    {
                        "contract_type": "current_system_status_summary",
                        "schema_version": 1,
                        "generated_at": "2026-05-16T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root, include_roots=("storage/dashboard/read_models/current_system_status_summary/latest.json",))

            self.assertEqual(index.summary["artifact_kind_counts"], {"current_system_status_summary": 1})
            self.assertEqual(index.records[0].producer_component, "current_system_status_summary")
            self.assertEqual(index.records[0].schema_ref, "1")

    def test_compressed_artifact_requires_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "storage" / "artifacts" / "sql_archive" / "partition.tar.zst"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(b"compressed-placeholder")

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].artifact_kind, "sql_archive")
            self.assertEqual(index.records[0].content_codec, "tar_zstd")
            self.assertEqual(index.records[0].content_format, "tar")
            self.assertEqual(index.records[0].read_mode, "restore_required")

    def test_write_artifact_index_outputs_jsonl_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("payload", encoding="utf-8")

            index = build_artifact_index(root=root)
            write_artifact_index(
                index,
                index_path=Path("storage/artifact_index/artifact_index.jsonl"),
                summary_path=Path("storage/artifact_index/artifact_index_summary.json"),
            )

            jsonl_path = root / "storage" / "artifact_index" / "artifact_index.jsonl"
            summary_path = root / "storage" / "artifact_index" / "artifact_index_summary.json"
            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["artifact_kind"], "example")
            self.assertEqual(summary["record_count"], 1)
            self.assertEqual(summary["contract_type"], "storage_artifact_index_summary_v1")


if __name__ == "__main__":
    unittest.main()
