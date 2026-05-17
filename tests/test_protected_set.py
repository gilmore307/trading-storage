from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index, write_artifact_index
from trading_storage.protected_set import (
    build_protected_set,
    load_artifact_index_jsonl,
    load_reference_sets,
    write_protected_set,
)


class ProtectedSetTests(unittest.TestCase):
    def test_unknown_metadata_artifact_is_protected_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "example_payload"}), encoding="utf-8")
            index = build_artifact_index(root=root, generated_at="2026-05-16T00:00:00Z")

            protected_set = build_protected_set(index, generated_at="2026-05-16T00:01:00Z")

            self.assertEqual(protected_set.summary["protected_count"], 1)
            self.assertEqual(protected_set.summary["mutation_allowed_count"], 0)
            self.assertEqual(protected_set.records[0].protected_reason_codes, ("unknown_metadata",))
            self.assertFalse(protected_set.records[0].mutation_allowed)

    def test_candidate_is_blocked_when_manually_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "example_payload"}), encoding="utf-8")
            index = build_artifact_index(root=root)

            record = index.records[0]
            protected_set = build_protected_set(
                index,
                manual_pins=(record.physical_path,),
                candidate_refs=(record.artifact_id,),
            )

            self.assertTrue(protected_set.records[0].candidate_requested)
            self.assertIn("manual_pin", protected_set.records[0].protected_reason_codes)
            self.assertEqual(protected_set.summary["candidate_count"], 1)
            self.assertEqual(protected_set.summary["candidate_protected_count"], 1)
            self.assertFalse(protected_set.summary["candidate_mutation_allowed"])

    def test_reference_file_reason_matches_lineage_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "dataset_snapshot" / "snapshot.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps(
                    {
                        "contract_type": "dataset_snapshot_manifest",
                        "lineage_refs": ["dataset://snapshot/monthly-2016-01"],
                    }
                ),
                encoding="utf-8",
            )
            reference_file = root / "refs.json"
            reference_file.write_text(
                json.dumps({"dataset_snapshot_or_split": ["dataset://snapshot/monthly-2016-01"]}),
                encoding="utf-8",
            )
            index = build_artifact_index(root=root)

            protected_set = build_protected_set(index, reference_sets=load_reference_sets(reference_file))

            self.assertIn("dataset_snapshot_or_split", protected_set.records[0].protected_reason_codes)
            self.assertEqual(protected_set.records[0].evidence_refs, ("dataset://snapshot/monthly-2016-01",))

    def test_clear_record_allows_candidate_mutation(self):
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
                    "reproducibility_class": "reproducible",
                }
            )

            protected_set = build_protected_set((clear_record,), candidate_refs=(clear_record.artifact_id,))

            self.assertEqual(protected_set.summary["candidate_clear_count"], 1)
            self.assertTrue(protected_set.summary["candidate_mutation_allowed"])
            self.assertTrue(protected_set.records[0].mutation_allowed)

    def test_jsonl_index_and_protected_set_outputs_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("payload", encoding="utf-8")
            index = build_artifact_index(root=root)
            write_artifact_index(index, index_path=Path("storage/artifact_index/artifact_index.jsonl"))
            records = load_artifact_index_jsonl(root / "storage" / "artifact_index" / "artifact_index.jsonl")
            protected_set = build_protected_set(records)
            write_protected_set(
                protected_set,
                output_path=root / "storage" / "protected_set" / "protected_set.json",
                summary_path=root / "storage" / "protected_set" / "protected_set_summary.json",
            )

            payload = json.loads((root / "storage" / "protected_set" / "protected_set.json").read_text(encoding="utf-8"))
            summary = json.loads((root / "storage" / "protected_set" / "protected_set_summary.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["contract_type"], "storage_protected_set_v1")
            self.assertEqual(summary["contract_type"], "storage_protected_set_summary_v1")
            self.assertEqual(summary["protected_count"], 1)


if __name__ == "__main__":
    unittest.main()
