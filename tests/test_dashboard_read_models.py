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
        "schema_ref": "storage/06_dashboard_cache/schemas/current_system_status_summary.schema.json",
    }
    payload.update(overrides)
    return payload


class DashboardReadModelTests(unittest.TestCase):
    def test_validate_common_envelope_returns_contract_type(self):
        contract_type = validate_dashboard_read_model(sample_payload(), now=FIXED_NOW)

        self.assertEqual(contract_type, "current_system_status_summary")

    def test_materializes_latest_schema_without_timestamped_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            materialized = materialize_dashboard_read_model(sample_payload(), storage_root=storage_root, now=FIXED_NOW)

            self.assertIsNone(materialized.snapshot_path)
            self.assertTrue(materialized.latest_path.exists())
            self.assertTrue(materialized.schema_path.exists())

            latest = json.loads(materialized.latest_path.read_text(encoding="utf-8"))
            schema = json.loads(materialized.schema_path.read_text(encoding="utf-8"))

            self.assertEqual(latest["contract_type"], "current_system_status_summary")
            self.assertEqual(schema["properties"]["contract_type"]["const"], "current_system_status_summary")
            self.assertFalse(materialized.snapshot_written)
            self.assertFalse(materialized.index_written)
            self.assertEqual(materialized.write_mode, "latest_only")
            self.assertEqual(materialized.storage_uri, "storage://trading-storage/06_dashboard_cache/read_models/current_system_status_summary.json")

    def test_latest_only_refresh_when_state_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            first = materialize_dashboard_read_model(sample_payload(), storage_root=storage_root, now=FIXED_NOW)
            second_payload = sample_payload(generated_at_utc="2026-05-12T00:00:30Z")
            second = materialize_dashboard_read_model(second_payload, storage_root=storage_root, now=FIXED_NOW)

            self.assertIsNone(first.snapshot_path)
            self.assertIsNone(second.snapshot_path)
            self.assertTrue(second.latest_path.exists())
            self.assertFalse(second.snapshot_written)
            self.assertFalse(second.index_written)
            self.assertEqual(second.write_mode, "latest_only")
            self.assertEqual(second.storage_uri, "storage://trading-storage/06_dashboard_cache/read_models/current_system_status_summary.json")

            latest = json.loads(second.latest_path.read_text(encoding="utf-8"))

            self.assertEqual(latest["generated_at_utc"], "2026-05-12T00:00:30Z")

    def test_state_change_replaces_current_file_without_snapshot_or_index_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            first = materialize_dashboard_read_model(sample_payload(), storage_root=storage_root, now=FIXED_NOW)
            changed = materialize_dashboard_read_model(
                sample_payload(
                    generated_at_utc="2026-05-12T00:01:00Z",
                    status="degraded",
                    summary="Dashboard read-model source is stale.",
                    chart_payload={"cards": [{"label": "stale", "value": 1}]},
                    freshness={"class": "fresh", "stale_after_seconds": 300, "status": "stale"},
                ),
                storage_root=storage_root,
                now=FIXED_NOW,
            )

            self.assertIsNone(first.snapshot_path)
            self.assertIsNone(changed.snapshot_path)
            self.assertFalse(changed.snapshot_written)
            self.assertFalse(changed.index_written)
            self.assertNotEqual(first.snapshot_state_hash, changed.snapshot_state_hash)
            latest = json.loads(changed.latest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest["status"], "degraded")

    def test_rejects_contract_type_mismatch(self):
        with self.assertRaises(DashboardReadModelError):
            validate_dashboard_read_model(
                sample_payload(),
                expected_contract_type="alert_exception_summary",
                now=FIXED_NOW,
            )

    def test_rejects_versioned_contract_alias(self):
        with self.assertRaises(DashboardReadModelError):
            validate_dashboard_read_model(
                sample_payload(
                    contract_type="current_system_status_summary_v1",
                    schema_ref="storage/06_dashboard_cache/schemas/current_system_status_summary_v1.schema.json",
                ),
                now=FIXED_NOW,
            )

    def test_accepts_registered_parked_contract_type(self):
        contract_type = validate_dashboard_read_model(
            sample_payload(
                contract_type="alert_exception_summary",
                schema_ref="storage/06_dashboard_cache/schemas/alert_exception_summary.schema.json",
            ),
            now=FIXED_NOW,
        )

        self.assertEqual(contract_type, "alert_exception_summary")

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
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/current_system_status_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
