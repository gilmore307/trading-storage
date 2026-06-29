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
            payload_path = root / "storage" / "02_control_plane" / "artifacts" / "component_completion_receipt" / "receipt-1.json"
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
            self.assertTrue(record.artifact_id.startswith("art_idx_"))
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
            latest = root / "storage" / "06_dashboard_cache" / "read_models" / "current_system_status_summary.json"
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

            index = build_artifact_index(root=root, include_roots=("storage/06_dashboard_cache/read_models/current_system_status_summary.json",))

            self.assertEqual(index.summary["artifact_kind_counts"], {"current_system_status_summary": 1})
            self.assertEqual(index.records[0].producer_component, "current_system_status_summary")
            self.assertEqual(index.records[0].schema_ref, "storage/06_dashboard_cache/schemas/current_system_status_summary.schema.json")
            self.assertEqual(index.records[0].schema_version, "1")
            self.assertEqual(index.records[0].retention_class, "dashboard_latest_retained")
            self.assertEqual(index.records[0].protected_reason_codes, ("dashboard_latest_snapshot",))

    def test_dashboard_snapshot_payload_is_ttl_delete_allowed_when_explicitly_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "storage" / "06_dashboard_cache" / "read_models" / "historical_task_progress_summary" / "snapshots" / "2026" / "05" / "16" / "20260516T000000Z.json"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(
                json.dumps(
                    {
                        "contract_type": "historical_task_progress_summary",
                        "schema_version": 1,
                        "generated_at": "2026-05-16T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root, include_roots=("storage/06_dashboard_cache/read_models/historical_task_progress_summary/snapshots/2026/05/16/20260516T000000Z.json",))

            self.assertEqual(index.records[0].retention_class, "ttl_delete_allowed")
            self.assertEqual(index.records[0].protected_reason_codes, ())

    def test_layer_one_two_artifacts_are_compress_and_retain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "model_01_market_context" / "bars.csv"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("date,symbol,close\n2016-01-04,SPY,200\n", encoding="utf-8")

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "compress_and_retain")
            self.assertEqual(index.records[0].protected_reason_codes, ())

    def test_layer_one_two_runtime_logs_are_ttl_delete_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "03_model_artifacts" / "model_01_sector_context" / "runs" / "run_1" / "stdout.log"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("run log\n", encoding="utf-8")

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "ttl_delete_allowed")
            self.assertEqual(index.records[0].protected_reason_codes, ())

    def test_explicit_storage_retention_and_reproducibility_metadata_are_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "01_source_data" / "fold_scoped" / "fold_aapl_2016" / "targets" / "AAPL" / "source.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps(
                    {
                        "contract_type": "target_symbol_source_payload",
                        "storage_retention_class": "fold_complete_delete_allowed",
                        "storage_reproducibility_class": "reproducible",
                    }
                ),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "fold_complete_delete_allowed")
            self.assertEqual(index.records[0].reproducibility_class, "reproducible")
            self.assertEqual(index.records[0].protected_reason_codes, ())

    def test_replay_result_summary_is_kept_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "05_replay_datasets" / "pipelines" / "model_03_target_state" / "result_summary.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps({"contract_type": "model_pipeline_replay_result_summary"}),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "keep_forever")
            self.assertEqual(index.records[0].protected_reason_codes, ("replay_result_summary",))

    def test_explicit_keep_forever_non_replay_uses_generic_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "03_model_artifacts" / "promoted_model" / "model.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps({"contract_type": "promoted_model_body", "storage_retention_class": "keep_forever"}),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "keep_forever")
            self.assertEqual(index.records[0].protected_reason_codes, ("keep_forever_retention",))

    def test_reusable_replay_layer_and_news_inputs_are_compress_and_retain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layer_input = root / "storage" / "05_replay_datasets" / "reusable_inputs" / "model_01_market_context" / "bars.csv"
            news_input = root / "storage" / "05_replay_datasets" / "reusable_inputs" / "event_news" / "news.jsonl"
            layer_input.parent.mkdir(parents=True, exist_ok=True)
            news_input.parent.mkdir(parents=True, exist_ok=True)
            layer_input.write_text("date,symbol,close\n2016-01-04,SPY,200\n", encoding="utf-8")
            news_input.write_text('{"headline":"example"}\n', encoding="utf-8")

            index = build_artifact_index(root=root)

            by_path = {record.physical_path: record for record in index.records}
            self.assertEqual(
                by_path["storage/05_replay_datasets/reusable_inputs/model_01_market_context/bars.csv"].retention_class,
                "compress_and_retain",
            )
            self.assertEqual(
                by_path["storage/05_replay_datasets/reusable_inputs/event_news/news.jsonl"].retention_class,
                "compress_and_retain",
            )

    def test_trading_economics_source_data_is_kept_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monthly = root / "storage" / "01_source_data" / "monthly_backfill" / "trading_economics_calendar_web" / "2016-01.jsonl"
            realtime = (
                root
                / "storage"
                / "01_source_data"
                / "realtime"
                / "trading_economics_calendar_web"
                / "runs"
                / "te_recent_calendar_refresh_20260526T103257Z"
                / "calendar.json"
            )
            monthly.parent.mkdir(parents=True, exist_ok=True)
            realtime.parent.mkdir(parents=True, exist_ok=True)
            monthly.write_text('{"event":"example"}\n', encoding="utf-8")
            realtime.write_text(json.dumps({"contract_type": "trading_economics_calendar_snapshot"}), encoding="utf-8")

            index = build_artifact_index(root=root)

            for record in index.records:
                self.assertEqual(record.retention_class, "keep_forever")
                self.assertEqual(record.protected_reason_codes, ("keep_forever_retention",))

    def test_model_specific_replay_option_snapshot_is_ttl_delete_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = (
                root
                / "storage"
                / "05_replay_datasets"
                / "model_specific_downloads"
                / "model_05_option_expression"
                / "option_snapshot"
                / "AAPL_2016-01-15.json"
            )
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"contract_type": "point_in_time_option_snapshot"}), encoding="utf-8")

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "ttl_delete_allowed")
            self.assertEqual(index.records[0].protected_reason_codes, ())

    def test_compressed_artifact_requires_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "storage" / "02_control_plane" / "artifacts" / "sql_archive" / "partition.tar.zst"
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
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "example" / "payload.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("payload", encoding="utf-8")

            index = build_artifact_index(root=root)
            write_artifact_index(
                index,
                index_path=Path("storage/90_lifecycle/artifact_index/artifact_index.jsonl"),
                summary_path=Path("storage/90_lifecycle/artifact_index/artifact_index_summary.json"),
            )

            jsonl_path = root / "storage" / "90_lifecycle" / "artifact_index" / "artifact_index.jsonl"
            summary_path = root / "storage" / "90_lifecycle" / "artifact_index" / "artifact_index_summary.json"
            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["artifact_kind"], "example")
            self.assertEqual(summary["record_count"], 1)
            self.assertEqual(summary["contract_type"], "storage_artifact_index_summary")

    def test_duplicate_explicit_artifact_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "storage" / "02_control_plane" / "artifacts" / "a" / "one.json"
            second = root / "storage" / "02_control_plane" / "artifacts" / "b" / "two.json"
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            first.write_text(json.dumps({"artifact_id": "duplicate", "contract_type": "example_payload"}), encoding="utf-8")
            second.write_text(json.dumps({"artifact_id": "duplicate", "contract_type": "example_payload"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate explicit artifact_id"):
                build_artifact_index(root=root)

    def test_implicit_artifact_ids_include_path_and_checksum_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "storage" / "02_control_plane" / "artifacts" / "a" / "same.json"
            second = root / "storage" / "02_control_plane" / "artifacts" / "b" / "same.json"
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"contract_type": "example_payload"}, sort_keys=True)
            first.write_text(payload, encoding="utf-8")
            second.write_text(payload, encoding="utf-8")

            index = build_artifact_index(root=root)

            self.assertEqual(len({record.artifact_id for record in index.records}), 2)
            self.assertTrue(all(record.artifact_id.startswith("art_idx_") for record in index.records))

    def test_m06_runtime_metadata_is_ttl_delete_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "storage" / "02_control_plane" / "artifacts" / "model_06_residual_event_governance" / "runtime_summary.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps(
                    {
                        "contract_type": "model_06_residual_event_governance_runtime_summary",
                        "model_layer": "model_06_residual_event_governance",
                    }
                ),
                encoding="utf-8",
            )

            index = build_artifact_index(root=root)

            self.assertEqual(index.records[0].retention_class, "ttl_delete_allowed")
            self.assertEqual(index.records[0].protected_reason_codes, ())


if __name__ == "__main__":
    unittest.main()
