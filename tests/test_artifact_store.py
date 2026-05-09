from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_store import (
    StorageArtifactError,
    canonical_json_bytes,
    store_completion_receipt_payload,
    store_json_artifact,
)


class ArtifactStoreTests(unittest.TestCase):
    def test_canonical_json_bytes_are_stable(self):
        left = canonical_json_bytes({"b": 2, "a": 1})
        right = canonical_json_bytes({"a": 1, "b": 2})
        self.assertEqual(left, right)
        self.assertTrue(left.endswith(b"\n"))

    def test_stores_json_artifact_and_returns_artifact_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            stored = store_json_artifact(
                {"contract_type": "sample_payload_v1", "value": 1},
                artifact_id="art_sample_001",
                artifact_type="sample_payload",
                producer_repo="trading-storage",
                producer_workflow="unit_test",
                manifest_id="manifest_sample_001",
                schema_ref="sample_payload_v1",
                storage_root=Path(tmp),
                produced_at="2026-05-09T10:00:00Z",
            )

            self.assertTrue(stored.local_path.exists())
            self.assertEqual(stored.artifact_ref["contract_version"], "artifact_ref_v1")
            self.assertEqual(stored.artifact_ref["artifact_id"], "art_sample_001")
            self.assertEqual(stored.artifact_ref["storage_uri"], "storage://trading-storage/artifacts/sample_payload/art_sample_001.json")
            self.assertEqual(stored.artifact_ref["schema_ref"], "sample_payload_v1")
            self.assertEqual(stored.artifact_ref["content_hash_sha256"], stored.content_hash)
            self.assertEqual(json.loads(stored.local_path.read_text(encoding="utf-8"))["value"], 1)

    def test_rejects_overwrite_with_different_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = {
                "artifact_id": "art_same",
                "artifact_type": "sample_payload",
                "producer_repo": "trading-storage",
                "producer_workflow": "unit_test",
                "manifest_id": "manifest_same",
                "schema_ref": "sample_payload_v1",
                "storage_root": Path(tmp),
            }
            store_json_artifact({"value": 1}, **kwargs)
            with self.assertRaises(StorageArtifactError):
                store_json_artifact({"value": 2}, **kwargs)

    def test_store_completion_receipt_payload_wraps_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            stored = store_completion_receipt_payload(
                {"run_id": "run_001", "status": "succeeded", "outputs": []},
                request_id="mgrreq_001",
                run_id="run_001",
                producer_repo="trading-data",
                workflow_id="01_feed_alpaca_bars",
                storage_root=Path(tmp),
            )
            payload = json.loads(stored.local_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["contract_type"], "component_completion_receipt_payload_v1")
            self.assertEqual(payload["request_id"], "mgrreq_001")
            self.assertEqual(stored.artifact_ref["artifact_type"], "component_completion_receipt")
            self.assertEqual(stored.artifact_ref["producer_repo"], "trading-data")
            self.assertEqual(stored.artifact_ref["producer_workflow"], "01_feed_alpaca_bars")


if __name__ == "__main__":
    unittest.main()
