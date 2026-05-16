from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.artifact_index import build_artifact_index, write_artifact_index
from trading_storage.lifecycle_planner import (
    load_policy_rules,
    load_protected_set_json,
    plan_storage_lifecycle,
    write_storage_lifecycle_plan,
)
from trading_storage.protected_set import build_protected_set, write_protected_set


class LifecyclePlannerTests(unittest.TestCase):
    def test_unknown_metadata_is_retained_as_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "example_payload"}), encoding="utf-8")
            index = build_artifact_index(root=root)

            plan = plan_storage_lifecycle(index, generated_at="2026-05-16T00:00:00Z")

            self.assertEqual(plan.summary["action_counts"], {"retain_protected": 1})
            self.assertEqual(plan.summary["mutation_performed"], False)
            self.assertIn("unknown_metadata", plan.records[0].protected_reason_codes)

    def test_unprotected_ttl_delete_artifact_becomes_quarantine_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "scratch" / "payload.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "scratch_payload"}), encoding="utf-8")
            index = build_artifact_index(root=root)
            record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "ttl_delete_allowed",
                    "reproducibility_class": "reproducible",
                }
            )

            plan = plan_storage_lifecycle((record,))

            self.assertEqual(plan.records[0].action, "quarantine_candidate")
            self.assertEqual(plan.records[0].rule_id, "quarantine_ttl_delete_allowed")
            self.assertFalse(plan.records[0].protected)

    def test_unprotected_source_artifact_becomes_compression_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "pit_source_data" / "payload.csv"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("a,b\n1,2\n", encoding="utf-8")
            index = build_artifact_index(root=root)
            record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "compress_and_retain",
                    "reproducibility_class": "provider_window_limited",
                }
            )

            plan = plan_storage_lifecycle((record,))

            self.assertEqual(plan.records[0].action, "compress_candidate")
            self.assertEqual(plan.records[0].rule_id, "compress_source_data")
            self.assertEqual(plan.summary["action_counts"], {"compress_candidate": 1})

    def test_receipts_are_retained_even_when_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "component_completion_receipt" / "receipt.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "component_completion_receipt_payload_v1"}), encoding="utf-8")
            index = build_artifact_index(root=root)
            record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "ttl_delete_allowed",
                }
            )

            plan = plan_storage_lifecycle((record,))

            self.assertEqual(plan.records[0].action, "retain_evidence")
            self.assertEqual(plan.records[0].rule_id, "retain_receipts_and_evidence")

    def test_policy_and_json_outputs_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "custom_kind" / "payload.dat"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("payload", encoding="utf-8")
            index = build_artifact_index(root=root)
            record = index.records[0].__class__(
                **{
                    **index.records[0].to_dict(),
                    "protected_reason_codes": (),
                    "retention_class": "custom_retention",
                }
            )
            policy_path = root / "policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "policy_id": "custom_policy",
                                "rule_id": "custom_archive",
                                "selector": {"retention_class": "custom_retention"},
                                "action": "archive_candidate",
                                "require_protected_set_clear": True,
                                "reason": "custom archive path",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            plan = plan_storage_lifecycle((record,), rules=load_policy_rules(policy_path))
            write_storage_lifecycle_plan(
                plan,
                output_path=root / "storage" / "lifecycle_plan" / "plan.json",
                summary_path=root / "storage" / "lifecycle_plan" / "summary.json",
            )

            payload = json.loads((root / "storage" / "lifecycle_plan" / "plan.json").read_text(encoding="utf-8"))
            summary = json.loads((root / "storage" / "lifecycle_plan" / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["records"][0]["action"], "archive_candidate")
            self.assertEqual(summary["contract_type"], "storage_lifecycle_plan_summary_v1")

    def test_loads_existing_index_and_protected_set_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "artifacts" / "example" / "payload.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("payload", encoding="utf-8")
            index = build_artifact_index(root=root)
            protected_set = build_protected_set(index)
            write_artifact_index(index, index_path=Path("storage/artifact_index/artifact_index.jsonl"))
            write_protected_set(protected_set, output_path=root / "storage" / "protected_set" / "protected_set.json")

            loaded_protected = load_protected_set_json(root / "storage" / "protected_set" / "protected_set.json")
            plan = plan_storage_lifecycle(index, protected_set=loaded_protected)

            self.assertEqual(plan.summary["protected_block_count"], 1)


if __name__ == "__main__":
    unittest.main()
