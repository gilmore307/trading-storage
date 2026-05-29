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


def _write_group_promotion_version(storage_root: Path) -> None:
    settlement_path = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "fold_settlement_runs"
        / "model_group_evaluation_fixture"
        / "fold_settlement_run.json"
    )
    review_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "promotion_review_runs"
        / "model_group_evaluation_fixture"
    )
    settlement_path.parent.mkdir(parents=True, exist_ok=True)
    review_root.mkdir(parents=True, exist_ok=True)
    settlement_path.write_text(
        json.dumps(
            {
                "contract_type": "fold_settlement_run",
                "target_symbol": "AAPL",
                "metrics": {
                    "decision_row_count": 5382,
                    "auroc": 0.5246,
                    "excess_return_total": 1.98,
                    "max_drawdown": -0.288,
                    "hit_rate": 0.52,
                    "brier_score": 0.24,
                    "pr_auc": 0.61,
                    "base_rate": 0.54,
                    "ece": 0.12,
                    "mce": 0.22,
                    "brier_reliability": 0.04,
                    "brier_resolution": 0.03,
                    "brier_uncertainty": 0.25,
                    "profit_factor": 1.4,
                    "return_per_decision": 0.0003,
                    "tail_loss_p05": -0.021,
                    "cost_sensitivity_2x": 1.2,
                    "worst_month_return": -0.18,
                    "month_slice_count": 6,
                    "data_integrity_status": "passed",
                    "leakage_check_status": "passed",
                    "decision_variable_schema_status": "passed",
                    "decision_intended_side_unknown_count": 0,
                    "decision_agency_unknown_count": 0,
                    "feature_column_count": 3,
                    "feature_row_count": 5382,
                    "feature_sample_count": 160,
                    "pca_available": True,
                    "pca_variance_top2": 0.81,
                    "pcoa_available": True,
                    "pcoa_variance_top2": 0.76,
                    "silhouette_outcome_label": 0.18,
                    "silhouette_decision_action": 0.09,
                    "feature_diagnostics": {
                        "feature_columns": ["feature_daily_return", "feature_momentum_7d", "feature_volume_rank_30d"],
                        "pca": {
                            "available": True,
                            "explained_variance_ratio": [0.62, 0.19],
                            "points": [{"x": -0.2, "y": 0.1, "outcome_label": 0, "decision_action": "skip"}],
                        },
                        "pcoa": {
                            "available": True,
                            "explained_variance_ratio": [0.51, 0.25],
                            "points": [{"x": -0.1, "y": 0.2, "outcome_label": 1, "decision_action": "trade"}],
                        },
                        "silhouette": {"outcome_label": 0.18, "decision_action": 0.09},
                    },
                    "predictive_diagnostics": {"base_rate": 0.54, "pr_auc": 0.61},
                    "calibration_diagnostics": {"ece": 0.12, "mce": 0.22},
                    "economic_diagnostics": {"profit_factor": 1.4, "tail_loss_p05": -0.021},
                    "data_integrity_diagnostics": {"status": "passed", "leakage_check_status": "passed"},
                    "temporal_stability_diagnostics": {"month_slice_count": 6, "worst_month_return": -0.18},
                    "baseline_comparison_diagnostics": {"candidate_minus_no_trade": 1.98},
                    "uncertainty_diagnostics": {"available": False, "reason": "single fold"},
                    "scorecards": {
                        "ranking_calibration": {
                            "auroc": 0.5246,
                            "pr_auc": 0.61,
                            "score_decile_return": [{"decile": 1, "row_count": 538, "excess_return_total": 0.42}],
                        },
                        "selection_quality": {
                            "taken_good_count": 2100,
                            "taken_bad_count": 1300,
                            "model_missed_good_count": 0,
                            "bad_fill_rate": 0.382353,
                            "profitable_opportunity_recall": 1.0,
                            "intended_operating_threshold_band": {"threshold": 0.7, "selected_count": 1800, "return_per_selected": 0.0012},
                        },
                        "economic_quality": {
                            "net_return_total": 2.1,
                            "baseline_return_total": 0.12,
                            "excess_return_total": 1.98,
                            "max_drawdown": -0.18,
                            "tail_loss_p05": -0.021,
                        },
                        "slices": {
                            "decision_intended_side": [
                                {"value": "long", "row_count": 3400, "excess_return_total": 1.7},
                                {"value": "flat", "row_count": 1982, "excess_return_total": 0.28},
                            ]
                        },
                    },
                    "evaluation_disagreement_report": {
                        "disagreement_count": 1,
                        "promotion_gate_basis": {"auroc_is_hard_gate": False},
                        "disagreements": [{"type": "auroc_below_old_gate_but_positive_utility", "severity": "notice"}],
                    },
                    "decision_variable_schema_diagnostics": {
                        "status": "passed",
                        "row_count": 5382,
                        "feature_namespace_leakage_status": "passed",
                        "feature_namespace_leakage_columns": [],
                        "coverage": {
                            "decision_intended_side": {"known_count": 5382, "unknown_count": 0, "values": {"long": 3400, "flat": 1982}},
                            "decision_intended_action": {"known_count": 5382, "unknown_count": 0, "values": {"open": 3400, "no_trade": 1982}},
                            "decision_disposition": {"known_count": 5382, "unknown_count": 0, "values": {"accepted": 3400, "rejected": 1982}},
                            "decision_agency": {"known_count": 5382, "unknown_count": 0, "values": {"model": 5382}},
                            "eval_action_class": {"known_count": 5382, "unknown_count": 0, "values": {"taken_good": 2100, "taken_bad": 1300, "avoided_bad": 1982}},
                            "eval_economic_class": {"known_count": 5382, "unknown_count": 0, "values": {"positive_excess": 2500, "negative_excess": 2882}},
                        },
                        "normalized_row_samples": [
                            {
                                "decision_intended_side": "long",
                                "decision_intended_action": "open",
                                "decision_disposition": "accepted",
                                "decision_agency": "model",
                                "replay_excess_return": 0.018,
                                "eval_action_class": "taken_good",
                                "eval_economic_class": "positive_excess",
                            }
                        ],
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_root / "promotion_evaluation_review.json").write_text(
        json.dumps(
            {
                "contract_type": "promotion_evaluation_review",
                "target_symbol": "AAPL",
                "recommendation": "insufficient_evidence",
                "rationale": "AUROC below gate and comparison evidence missing.",
                "blocking_issues": ["auroc_below_minimum", "missing anonymous comparison"],
                "settlement_run_ref": str(settlement_path),
                "created_at_utc": "2026-05-29T00:04:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_root / "promotion_eligibility_decision.json").write_text(
        json.dumps(
            {
                "contract_type": "promotion_eligibility_decision",
                "fold_id": "fold_2016-01_2016-06",
                "target_symbol": "AAPL",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2016-06",
                "decision_status": "deferred",
                "agent_review_recommendation": "insufficient_evidence",
                "decision_reason": "AUROC below gate and comparison evidence missing.",
                "settlement_run_ref": str(settlement_path),
                "created_at_utc": "2026-05-29T00:04:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_mismatched_group_promotion_version(storage_root: Path) -> None:
    replay_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "replay_execution_runs"
        / "crypto_replay_fixture"
    )
    replay_root.mkdir(parents=True, exist_ok=True)
    replay_receipt_path = replay_root / "replay_execution_receipt.json"
    replay_receipt_path.write_text(
        json.dumps(
            {
                "contract_type": "evaluation_replay_execution_run",
                "candidate_model_ref": "storage://trading-manager/model_group/2016-01_2016-06",
                "target_refs": ["BTC", "ETH", "SOL"],
                "decision_rows_ref": str(replay_root / "decision_rows.jsonl"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settlement_path = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "fold_settlement_runs"
        / "model_group_evaluation_mismatch"
        / "fold_settlement_run.json"
    )
    review_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "promotion_review_runs"
        / "model_group_evaluation_mismatch"
    )
    settlement_path.parent.mkdir(parents=True, exist_ok=True)
    review_root.mkdir(parents=True, exist_ok=True)
    settlement_path.write_text(
        json.dumps(
            {
                "contract_type": "fold_settlement_run",
                "target_symbol": "AAPL",
                "replay_result_ref": str(replay_receipt_path),
                "metrics": {"decision_row_count": 5382, "auroc": 0.52},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_root / "promotion_evaluation_review.json").write_text(
        json.dumps(
            {
                "contract_type": "promotion_evaluation_review",
                "target_symbol": "AAPL",
                "recommendation": "insufficient_evidence",
                "settlement_run_ref": str(settlement_path),
                "created_at_utc": "2026-05-29T00:05:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_root / "promotion_eligibility_decision.json").write_text(
        json.dumps(
            {
                "contract_type": "promotion_eligibility_decision",
                "fold_id": "fold_2016-01_2016-06",
                "target_symbol": "AAPL",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2016-06",
                "decision_status": "deferred",
                "agent_review_recommendation": "insufficient_evidence",
                "settlement_run_ref": str(settlement_path),
                "replay_validation_ref": str(replay_receipt_path),
                "created_at_utc": "2026-05-29T00:05:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )


class DashboardModelsTests(unittest.TestCase):
    def test_builds_model_layer_readiness_from_existing_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)

            payload = build_model_layer_readiness_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["contract_type"], MODEL_LAYER_READINESS_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_LAYER_READINESS_CONTRACT)
            layers = payload["chart_payload"]["layers"]
            self.assertEqual(len(layers), 10)
            layer_five = next(layer for layer in layers if layer["layer"] == 5)
            self.assertEqual(layer_five["versions"][0]["version_id"], "2016-fold1:model_05_alpha_confidence")
            self.assertEqual(layer_five["promotion"]["status"], "deferred")
            self.assertEqual(len(payload["chart_payload"]["group_versions"]), 1)

    def test_builds_model_promotion_posture_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)

            payload = build_model_promotion_posture_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["contract_type"], MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertEqual(len(payload["chart_payload"]["models"]), 10)
            layer_five = next(row for row in payload["chart_payload"]["models"] if row["layer"] == 5)
            self.assertEqual(layer_five["version_id"], "2016-fold1:model_05_alpha_confidence")
            self.assertEqual(layer_five["evaluation_status"], "ready")
            self.assertEqual(payload["chart_payload"]["status_counts"], {"deferred": 1})
            self.assertEqual(payload["chart_payload"]["identity_counts"], {"retired": 1})
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["version_label"], "AAPL 2016 fold1")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["auroc"], 0.5246)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["pr_auc"], 0.61)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["data_integrity_status"], "passed")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["pca_variance_top2"], 0.81)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["silhouette_outcome_label"], 0.18)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["decision_variable_schema_status"], "passed")
            variable_diagnostics = payload["chart_payload"]["group_versions"][0]["metrics"]["decision_variable_schema_diagnostics"]
            self.assertEqual(variable_diagnostics["coverage"]["decision_intended_side"]["values"]["long"], 3400)
            self.assertEqual(variable_diagnostics["coverage"]["eval_action_class"]["values"]["taken_good"], 2100)
            scorecards = payload["chart_payload"]["group_versions"][0]["metrics"]["scorecards"]
            self.assertEqual(scorecards["selection_quality"]["taken_good_count"], 2100)
            self.assertFalse(payload["chart_payload"]["group_versions"][0]["metrics"]["evaluation_disagreement_report"]["promotion_gate_basis"]["auroc_is_hard_gate"])

    def test_model_group_versions_are_fold_level_not_review_run_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)
            source_root = (
                storage_root
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "promotion_review_runs"
                / "model_group_evaluation_fixture"
            )
            duplicate_root = source_root.parent / "model_group_evaluation_fixture_retry"
            duplicate_root.mkdir(parents=True, exist_ok=True)
            for filename in ["promotion_evaluation_review.json", "promotion_eligibility_decision.json"]:
                duplicate_root.joinpath(filename).write_text(
                    source_root.joinpath(filename).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:04:00Z",
            )

            self.assertEqual(len(payload["chart_payload"]["group_versions"]), 1)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["version_label"], "AAPL 2016 fold1")

    def test_model_group_versions_skip_replay_target_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_mismatched_group_promotion_version(storage_root)

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:06:00Z",
            )

            self.assertEqual(payload["chart_payload"]["group_versions"], [])
            self.assertEqual(payload["chart_payload"]["status_counts"], {})

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
