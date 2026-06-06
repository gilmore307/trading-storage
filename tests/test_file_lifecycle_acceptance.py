from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from trading_storage.file_lifecycle_acceptance import build_file_lifecycle_acceptance
from trading_storage.protected_set import build_protected_set
from trading_storage.artifact_index import build_artifact_index


class FileLifecycleAcceptanceTests(unittest.TestCase):
    def test_acceptance_writes_evidence_and_compresses_only_copies(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            source_dir = root / "storage" / "02_control_plane" / "artifacts" / "layer_01_market_regime"
            source_dir.mkdir(parents=True)
            source = source_dir / "layer_01_payload.json"
            source.write_text('{"contract_type":"layer_01_source_data","model_layer":"layer_01_market_regime"}\n', encoding="utf-8")
            snapshot_dir = root / "storage" / "06_dashboard_cache" / "read_models" / "current_status" / "snapshots" / "2026" / "05" / "01"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "20260501T000000Z.json").write_text('{"contract_type":"current_status"}\n', encoding="utf-8")

            acceptance = build_file_lifecycle_acceptance(
                root=root,
                apply_compression=True,
                generated_at="2026-05-16T10:00:00Z",
            )
            summary = acceptance.summary

            self.assertEqual(summary["contract_type"], "storage_file_lifecycle_acceptance_summary")
            self.assertEqual(summary["artifact_record_count"], 2)
            self.assertEqual(summary["lifecycle_action_counts"], {"compress_candidate": 1, "quarantine_candidate": 1})
            self.assertEqual(summary["compression_status_counts"], {"succeeded": 1})
            self.assertTrue(summary["compressed_copy_mutation_performed"])
            self.assertFalse(summary["delete_original_performed"])
            self.assertFalse(summary["artifact_index_updated"])
            self.assertFalse(summary["quarantine_move_performed"])
            self.assertFalse(summary["sql_mutation_performed"])
            self.assertFalse(summary["dashboard_snapshot_delete_performed"])
            self.assertTrue(source.exists())
            compressed = list((root / "storage" / "90_lifecycle" / "archive" / "compressed").rglob("*.zst"))
            self.assertEqual(len(compressed), 1)
            self.assertTrue((root / "storage" / "90_lifecycle" / "execution" / "file_lifecycle_acceptance_summary.json").exists())
            saved = json.loads((root / "storage" / "90_lifecycle" / "execution" / "file_lifecycle_acceptance_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["compression_status_counts"], {"succeeded": 1})

    def test_acceptance_resolves_dashboard_outputs_under_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root, tempfile.TemporaryDirectory() as raw_cwd:
            root = Path(raw_root)
            cwd = Path(raw_cwd)
            artifact_dir = root / "storage" / "02_control_plane" / "artifacts"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "payload.json").write_text('{"contract_type":"unknown"}\n', encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                build_file_lifecycle_acceptance(root=root, generated_at="2026-05-16T10:00:00Z")
            finally:
                os.chdir(previous_cwd)

            self.assertTrue((root / "storage" / "06_dashboard_cache" / "lifecycle" / "dashboard_snapshot_prune_plan.json").exists())
            self.assertTrue((root / "storage" / "06_dashboard_cache" / "lifecycle" / "dashboard_snapshot_prune_summary.json").exists())
            self.assertFalse((cwd / "storage" / "06_dashboard_cache" / "lifecycle" / "dashboard_snapshot_prune_plan.json").exists())

    def test_dashboard_latest_reason_is_protected_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            latest = root / "storage" / "06_dashboard_cache" / "read_models" / "current_status.json"
            latest.parent.mkdir(parents=True)
            latest.write_text('{"contract_type":"current_status"}\n', encoding="utf-8")

            index = build_artifact_index(root=root, include_roots=("storage/06_dashboard_cache/read_models/current_status.json",))
            protected = build_protected_set(index)

            self.assertEqual(index.records[0].retention_class, "dashboard_latest_retained")
            self.assertEqual(protected.records[0].protected_reason_codes, ("dashboard_latest_snapshot",))
            self.assertTrue(protected.records[0].protected)

    def test_dashboard_prune_apply_requires_approval_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            artifact_dir = root / "storage" / "02_control_plane" / "artifacts"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "payload.json").write_text('{"contract_type":"unknown"}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "approval_ref is required"):
                build_file_lifecycle_acceptance(root=root, apply_dashboard_prune=True)


if __name__ == "__main__":
    unittest.main()
