from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index
from trading_storage.lifecycle_planner import plan_storage_lifecycle
from trading_storage.protected_set import ProtectedArtifact, ProtectedSet
from trading_storage.quarantine_delete_executor import build_quarantine_delete_result
from trading_storage.quarantine_recheck import build_quarantine_recheck_evidence


class QuarantineDeleteExecutorTests(unittest.TestCase):
    def test_clear_recheck_gets_planned_receipts_but_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "scratch" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text('{"contract_type":"scratch_payload"}\n', encoding="utf-8")
            index = build_artifact_index(root=root)
            clear_record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "ttl_delete_allowed",
                }
            )
            plan = plan_storage_lifecycle((clear_record,), generated_at="2026-05-17T00:00:00Z")
            final_set = ProtectedSet(
                contract_type="storage_protected_set_v1",
                generated_at="2026-05-17T00:01:00Z",
                source_index_generated_at=None,
                records=(
                    ProtectedArtifact(
                        artifact_id=clear_record.artifact_id,
                        artifact_kind=clear_record.artifact_kind,
                        artifact_uri=clear_record.artifact_uri,
                        physical_path=clear_record.physical_path,
                        protected_reason_codes=(),
                        candidate_requested=True,
                        protected=False,
                        mutation_allowed=True,
                    ),
                ),
            )
            evidence = build_quarantine_recheck_evidence(plan, final_protected_set=final_set, generated_at="2026-05-17T00:02:00Z")

            result = build_quarantine_delete_result(evidence, generated_at="2026-05-17T00:03:00Z")

            self.assertEqual(result.summary["quarantine_status_counts"], {"planned_not_executed": 1})
            self.assertEqual(result.summary["deletion_status_counts"], {"planned_not_executed": 1})
            self.assertEqual(result.summary["tombstone_draft_count"], 1)
            self.assertFalse(result.summary["mutation_performed"])
            self.assertFalse(result.summary["quarantine_move_performed"])
            self.assertFalse(result.summary["delete_performed"])
            self.assertFalse(result.deletion_receipts[0].delete_performed)

    def test_pending_recheck_blocks_deletion_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "scratch" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text('{"contract_type":"scratch_payload"}\n', encoding="utf-8")
            index = build_artifact_index(root=root)
            clear_record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "ttl_delete_allowed",
                }
            )
            plan = plan_storage_lifecycle((clear_record,), generated_at="2026-05-17T00:00:00Z")
            evidence = build_quarantine_recheck_evidence(plan, generated_at="2026-05-17T00:02:00Z")

            result = build_quarantine_delete_result(evidence, generated_at="2026-05-17T00:03:00Z")

            self.assertEqual(result.summary["quarantine_status_counts"], {"blocked_final_recheck": 1})
            self.assertEqual(result.summary["deletion_status_counts"], {"blocked_final_recheck": 1})
            self.assertEqual(result.summary["tombstone_draft_count"], 0)
            self.assertFalse(result.summary["mutation_performed"])


if __name__ == "__main__":
    unittest.main()
