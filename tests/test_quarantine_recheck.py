from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index
from trading_storage.lifecycle_planner import plan_storage_lifecycle, write_storage_lifecycle_plan
from trading_storage.protected_set import build_protected_set, write_protected_set
from trading_storage.quarantine_recheck import (
    build_quarantine_recheck_evidence,
    load_storage_lifecycle_plan_json,
    write_quarantine_recheck_evidence,
)


class QuarantineRecheckTests(unittest.TestCase):
    def test_protected_plan_record_blocks_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "example" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "example_payload"}), encoding="utf-8")
            plan = plan_storage_lifecycle(build_artifact_index(root=root))

            evidence = build_quarantine_recheck_evidence(plan, generated_at="2026-05-16T00:00:00Z")

            self.assertEqual(evidence.summary["state_counts"], {"blocked_initial_protection": 1})
            self.assertEqual(evidence.summary["deletion_allowed_count"], 0)
            self.assertFalse(evidence.records[0].mutation_performed)
            self.assertFalse(evidence.records[0].deletion_allowed)

    def test_clear_quarantine_candidate_requires_final_recheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "scratch" / "payload.json"
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
            plan = plan_storage_lifecycle((clear_record,))

            evidence = build_quarantine_recheck_evidence(plan)

            self.assertEqual(evidence.records[0].quarantine_state, "dry_run_candidate_pending_recheck")
            self.assertEqual(evidence.records[0].recheck_status, "not_performed")
            self.assertTrue(evidence.records[0].recheck_required)
            self.assertFalse(evidence.records[0].deletion_allowed)

    def test_final_recheck_can_block_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "scratch" / "payload.json"
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
            protected_record = clear_record.__class__(
                **{
                    **clear_record.to_dict(),
                    "protected_reason_codes": ("manual_pin",),
                }
            )
            final_protected_set = build_protected_set((protected_record,))

            evidence = build_quarantine_recheck_evidence(plan, final_protected_set=final_protected_set)

            self.assertEqual(evidence.records[0].quarantine_state, "blocked_final_recheck")
            self.assertEqual(evidence.records[0].recheck_status, "blocked")
            self.assertEqual(evidence.records[0].final_protected_reason_codes, ("manual_pin",))
            self.assertFalse(evidence.records[0].deletion_allowed)

    def test_final_recheck_clear_still_does_not_authorize_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "scratch" / "payload.json"
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
            final_protected_set = build_protected_set((clear_record,))

            evidence = build_quarantine_recheck_evidence(plan, final_protected_set=final_protected_set)

            self.assertEqual(evidence.records[0].quarantine_state, "dry_run_recheck_clear")
            self.assertEqual(evidence.records[0].recheck_status, "clear")
            self.assertEqual(evidence.summary["final_recheck_clear_count"], 1)
            self.assertEqual(evidence.summary["deletion_allowed_count"], 0)
            self.assertFalse(evidence.records[0].mutation_performed)

    def test_non_quarantine_actions_are_not_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "pit_source_data" / "payload.csv"
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
            plan = plan_storage_lifecycle((clear_record,))

            evidence = build_quarantine_recheck_evidence(plan)

            self.assertEqual(evidence.records[0].quarantine_state, "not_quarantine_candidate")
            self.assertEqual(evidence.records[0].recheck_status, "not_applicable")
            self.assertFalse(evidence.records[0].quarantine_candidate)

    def test_lifecycle_plan_and_evidence_outputs_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "scratch" / "payload.json"
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
            plan = plan_storage_lifecycle((clear_record,), generated_at="2026-05-16T00:00:00Z")
            write_storage_lifecycle_plan(plan, output_path=root / "storage" / "lifecycle_plan" / "plan.json")
            loaded_plan = load_storage_lifecycle_plan_json(root / "storage" / "lifecycle_plan" / "plan.json")
            final_protected_set = build_protected_set((clear_record,), generated_at="2026-05-16T00:01:00Z")
            write_protected_set(final_protected_set, output_path=root / "storage" / "protected_set" / "protected_set.json")

            evidence = build_quarantine_recheck_evidence(loaded_plan, final_protected_set=final_protected_set)
            write_quarantine_recheck_evidence(
                evidence,
                output_path=root / "storage" / "quarantine_recheck" / "evidence.json",
                summary_path=root / "storage" / "quarantine_recheck" / "summary.json",
            )

            payload = json.loads((root / "storage" / "quarantine_recheck" / "evidence.json").read_text(encoding="utf-8"))
            summary = json.loads((root / "storage" / "quarantine_recheck" / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["contract_type"], "storage_quarantine_recheck_evidence")
            self.assertEqual(payload["source_lifecycle_plan_generated_at"], "2026-05-16T00:00:00Z")
            self.assertEqual(payload["final_protected_set_generated_at"], "2026-05-16T00:01:00Z")
            self.assertEqual(summary["contract_type"], "storage_quarantine_recheck_summary")


if __name__ == "__main__":
    unittest.main()
