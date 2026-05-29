from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_models import (
    MODEL_LAYER_READINESS_CONTRACT,
    MODEL_PROMOTION_POSTURE_CONTRACT,
    build_model_layer_readiness_summary,
    build_model_promotion_posture_summary,
    refresh_model_layer_readiness_summary_read_model,
    refresh_model_promotion_posture_summary_read_model,
)
from trading_storage.dashboard_read_models import validate_dashboard_read_model


def _write_latest(storage_root: Path, contract_type: str, payload: dict) -> None:
    path = storage_root / "06_dashboard_cache" / "read_models" / contract_type / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _historical_payload() -> dict:
    return {
        "contract_type": "historical_task_progress_summary",
        "schema_version": 1,
        "generated_at_utc": "2026-05-29T00:00:00Z",
        "source_system": "trading-manager",
        "status": "running",
        "severity": "info",
        "summary": "Historical modeling is running.",
        "chart_payload": {
            "current_month": "2016-fold1",
            "active_task": {"layer": 5},
            "task_timeline": [
                {
                    "task_uid": "l5-train",
                    "month": "2016-fold1",
                    "task_id": "layer_05_alpha_confidence.model_generation.train",
                    "task_label": "Layer 5 Alpha Confidence Model",
                    "task_state": "current",
                    "status": "running",
                    "stage_type": "model_generation",
                    "layer": 5,
                    "status_updated_at_utc": "2026-05-29T00:01:00Z",
                    "detail": {"receipt_refs": ["receipt://l5-train"]},
                },
                {
                    "task_uid": "eval",
                    "month": "2016-fold1",
                    "task_id": "model_group.evaluation",
                    "task_label": "Model Evaluation",
                    "task_state": "future",
                    "status": "ready",
                    "stage_type": "model_evaluation",
                    "status_updated_at_utc": "2026-05-29T00:02:00Z",
                },
                {
                    "task_uid": "promo",
                    "month": "2016-fold1",
                    "task_id": "model_group.promotion",
                    "task_label": "Model Promotion",
                    "task_state": "future",
                    "status": "blocked",
                    "stage_type": "promotion_review",
                    "status_updated_at_utc": "2026-05-29T00:03:00Z",
                },
            ],
        },
        "profile_refs": [],
        "issue_refs": [],
        "diagnostic_refs": [],
        "lineage_refs": [],
        "freshness": {"class": "runtime_status_snapshot", "status": "fresh", "stale_after_seconds": 900},
        "schema_ref": "storage/06_dashboard_cache/schemas/historical_task_progress_summary.schema.json",
    }


def _runtime_payload() -> dict:
    return {
        "contract_type": "execution_realtime_trading_runtime_status",
        "schema_version": 1,
        "generated_at_utc": "2026-05-29T00:00:00Z",
        "source_system": "trading-storage",
        "status": "waiting_for_promoted_model",
        "summary": "Execution runtime is waiting for a promoted model.",
        "chart_payload": {
            "runtime_status": "waiting_for_promoted_model",
            "next_gate": "write_active_model_config_after_promotion",
            "active_model_pointer": {"selected_active_model_ref": None},
        },
        "profile_refs": [],
        "issue_refs": [],
        "diagnostic_refs": [],
        "lineage_refs": [],
        "freshness": {"class": "execution_runtime_status_snapshot", "status": "fresh", "stale_after_seconds": 120},
        "schema_ref": "storage/06_dashboard_cache/schemas/execution_realtime_trading_runtime_status.schema.json",
    }


class DashboardModelsTests(unittest.TestCase):
    def test_builds_model_layer_readiness_from_existing_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            payload = build_model_layer_readiness_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["contract_type"], MODEL_LAYER_READINESS_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_LAYER_READINESS_CONTRACT)
            layers = payload["chart_payload"]["layers"]
            self.assertEqual(len(layers), 10)
            layer_five = next(layer for layer in layers if layer["layer"] == 5)
            self.assertEqual(layer_five["versions"][0]["version_id"], "2016-fold1:model_05_alpha_confidence")
            self.assertEqual(layer_five["promotion"]["status"], "blocked")

    def test_builds_model_promotion_posture_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            payload = build_model_promotion_posture_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["contract_type"], MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertEqual(len(payload["chart_payload"]["models"]), 10)
            layer_five = next(row for row in payload["chart_payload"]["models"] if row["layer"] == 5)
            self.assertEqual(layer_five["version_id"], "2016-fold1:model_05_alpha_confidence")
            self.assertEqual(layer_five["evaluation_status"], "ready")

    def test_refresh_materializes_model_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            layer_receipt = refresh_model_layer_readiness_summary_read_model(storage_root=storage_root)
            promotion_receipt = refresh_model_promotion_posture_summary_read_model(storage_root=storage_root)

            self.assertEqual(layer_receipt["refreshed_contract_type"], MODEL_LAYER_READINESS_CONTRACT)
            self.assertEqual(promotion_receipt["refreshed_contract_type"], MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_layer_readiness_summary/latest.json").exists())
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_promotion_posture_summary/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
