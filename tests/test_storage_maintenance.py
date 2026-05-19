from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.storage_maintenance import run_storage_maintenance, write_storage_maintenance_summary


class StorageMaintenanceTests(unittest.TestCase):
    def test_maintenance_summary_preserves_side_effect_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            summary = run_storage_maintenance(root=root, generated_at_utc="2026-05-19T12:00:00Z")

        self.assertEqual(summary.contract_type, "storage_scheduled_maintenance_summary")
        self.assertTrue(summary.local_retention_enabled)
        self.assertFalse(summary.local_retention_apply)
        self.assertEqual(summary.fold_sql_backup_phase_status, "not_configured")
        self.assertEqual(summary.deletion_phase_status, "local_retention_only")
        self.assertFalse(summary.provider_calls_performed)
        self.assertFalse(summary.model_activation_performed)
        self.assertFalse(summary.broker_execution_performed)
        self.assertFalse(summary.account_mutation_performed)

    def test_maintenance_summary_writes_output_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            summary = run_storage_maintenance(root=root, generated_at_utc="2026-05-19T12:00:00Z")
            write_storage_maintenance_summary(summary, output_path=Path("storage/maintenance/summary.json"), root=root)
            payload = json.loads((root / "storage" / "maintenance" / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["contract_type"], "storage_scheduled_maintenance_summary")
        self.assertEqual(payload["generated_at_utc"], "2026-05-19T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
