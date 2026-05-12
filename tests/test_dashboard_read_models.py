from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trading_storage.dashboard_read_models import (
    DashboardReadModelError,
    materialize_dashboard_read_model,
    validate_dashboard_read_model,
)


FIXED_NOW = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)


def sample_payload(**overrides):
    payload = {
        "contract_type": "current_system_status_summary",
        "schema_version": 1,
        "generated_at_utc": "2026-05-12T00:00:00Z",
        "source_system": "trading-manager",
        "status": "healthy",
        "severity": "info",
        "summary": "Historical scheduler is parked behind promotion evidence gates.",
        "chart_payload": {"cards": [{"label": "ready", "value": 1}]},
        "profile_refs": [],
        "issue_refs": [],
        "diagnostic_refs": [],
        "lineage_refs": [{"ref": "manager_status_snapshot"}],
        "freshness": {"class": "fresh", "stale_after_seconds": 300, "status": "healthy"},
        "schema_ref": "storage/dashboard/schemas/current_system_status_summary.schema.json",
    }
    payload.update(overrides)
    return payload


class DashboardReadModelTests(unittest.TestCase):
    def test_validate_common_envelope_returns_contract_type(self):
        contract_type = validate_dashboard_read_model(sample_payload(), now=FIXED_NOW)

        self.assertEqual(contract_type, "current_system_status_summary")

    def test_materializes_snapshot_latest_schema_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            materialized = materialize_dashboard_read_model(sample_payload(), storage_root=storage_root, now=FIXED_NOW)

            self.assertTrue(materialized.snapshot_path.exists())
            self.assertTrue(materialized.latest_path.exists())
            self.assertTrue(materialized.schema_path.exists())
            self.assertTrue(materialized.index_path.exists())
            self.assertEqual(materialized.latest_path.read_bytes(), materialized.snapshot_path.read_bytes())

            snapshot = json.loads(materialized.snapshot_path.read_text(encoding="utf-8"))
            schema = json.loads(materialized.schema_path.read_text(encoding="utf-8"))
            index_rows = [json.loads(line) for line in materialized.index_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(snapshot["contract_type"], "current_system_status_summary")
            self.assertEqual(schema["properties"]["contract_type"]["const"], "current_system_status_summary")
            self.assertEqual(len(index_rows), 1)
            self.assertEqual(index_rows[0]["snapshot_uri"], materialized.storage_uri)
            self.assertEqual(index_rows[0]["content_hash_sha256"], materialized.content_hash)
            self.assertEqual(index_rows[0]["byte_count"], materialized.byte_count)

    def test_rejects_contract_type_mismatch(self):
        with self.assertRaises(DashboardReadModelError):
            validate_dashboard_read_model(
                sample_payload(),
                expected_contract_type="alert_exception_summary",
                now=FIXED_NOW,
            )

    def test_rejects_future_timestamp_beyond_skew(self):
        with self.assertRaises(DashboardReadModelError):
            validate_dashboard_read_model(
                sample_payload(generated_at_utc="2026-05-12T12:10:01Z"),
                now=FIXED_NOW,
            )

    def test_rejects_secret_like_field(self):
        with self.assertRaises(DashboardReadModelError):
            validate_dashboard_read_model(
                sample_payload(chart_payload={"api_key": "should_not_be_here"}),
                now=FIXED_NOW,
            )

    def test_rejects_unsafe_contract_shape(self):
        with self.assertRaises(DashboardReadModelError):
            validate_dashboard_read_model(
                sample_payload(contract_type="../current_system_status_summary"),
                now=FIXED_NOW,
            )

    def test_cli_materializes_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp) / "storage"
            payload_path = Path(tmp) / "payload.json"
            payload_path.write_text(json.dumps(sample_payload()), encoding="utf-8")

            from scripts.dashboard.materialize_read_model import main

            with contextlib.redirect_stdout(io.StringIO()):
                result = main([str(payload_path), "--contract-type", "current_system_status_summary", "--storage-root", str(storage_root)])

            self.assertEqual(result, 0)
            self.assertTrue((storage_root / "dashboard/read_models/current_system_status_summary/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
