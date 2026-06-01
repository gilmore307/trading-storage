from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_models import (
    LAYER_EVALUATION_SUMMARY_CONTRACT,
    MODEL_LAYER_EVALUATION_CONTRACT,
    MODEL_LAYER_READINESS_CONTRACT,
    MODEL_PROMOTION_POSTURE_CONTRACT,
    build_model_layer_evaluation_summary,
    build_model_layer_readiness_summary,
    build_model_promotion_posture_summary,
    materialize_layer_evaluation_summary_artifacts,
    refresh_model_layer_evaluation_summary_read_model,
    refresh_model_layer_readiness_summary_read_model,
    refresh_model_promotion_posture_summary_read_model,
)
from trading_storage.dashboard_read_models import validate_dashboard_read_model


def _write_latest(storage_root: Path, contract_type: str, payload: dict) -> None:
    path = storage_root / "06_dashboard_cache" / "read_models" / contract_type / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_legacy_layer_evaluation(storage_root: Path, model_id: str = "model_05_alpha_confidence") -> None:
    path = storage_root / "03_model_artifacts" / "runtime" / model_id / "evaluation_summary_2016-01.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_status": "completed",
                "request_status": "completed",
                "eval_run_id": "mdevrun_fixture",
                "evidence_source": "postgresql:trading_model.model_05_alpha_confidence",
                "acceptance_thresholds": {
                    "minimum_eval_labels": 200.0,
                    "minimum_rank_ic": 0.01,
                },
                "metric_value_summary": {
                    "rank_ic_by_horizon": {"count": 4, "mean": 0.021, "min": -0.004, "max": 0.044},
                    "decile_spread_after_cost": {"count": 1, "mean": 0.003},
                    "purged_embargoed_cv": {"count": 1, "mean": 1.0},
                },
                "threshold_results": {
                    "minimum_eval_labels": {"actual": 2410.0, "threshold": 200.0, "passed": True},
                    "minimum_rank_ic": {"actual": 0.021, "threshold": 0.01, "passed": True},
                },
                "tables": {
                    "model_dataset_request": 1,
                    "model_dataset_snapshot": 1,
                    "model_dataset_split": 3,
                    "model_eval_label": 2410,
                    "model_eval_run": 1,
                    "model_promotion_metric": 3,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_local_layer_evaluation(storage_root: Path, model_id: str = "model_05_alpha_confidence") -> None:
    path = storage_root / "03_model_artifacts" / "runtime" / model_id / "evaluation_summary_2016-01.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "summary": {
                    "layer_number": 5,
                    "model_surface": "model_05_alpha_confidence",
                    "model_id": model_id,
                    "evidence_source": "storage_runtime_model_rows_fixture_outcomes",
                    "model_row_count": 77837,
                    "outcome_row_count": 77837,
                    "label_row_count": 77837,
                    "label_join_coverage_rate": 1.0,
                    "leakage_check_passed": True,
                    "promotion_gate_state": "deferred",
                    "reason_codes": ["fixture_or_local_evidence_must_defer"],
                },
                "labels": [{"label_id": "label_fixture"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_runtime_model_artifact(storage_root: Path, model_id: str = "model_05_alpha_confidence") -> None:
    path = storage_root / "03_model_artifacts" / "runtime" / model_id / "after_cost_alpha_model_fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model_id": model_id,
                "artifacts_by_horizon": {
                    "10min": {
                        "booster_model": "\n".join(
                            [
                                "tree",
                                "feature_importances:",
                                "3_target_direction_score_10min=42",
                                "1_market_direction_score=17",
                                "",
                                "parameters:",
                            ]
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


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
                    "task_state": "completed",
                    "status": "succeeded",
                    "stage_type": "model_generation",
                    "layer": 5,
                    "status_updated_at_utc": "2026-05-29T00:01:00Z",
                    "detail": {
                        "receipt_refs": ["storage/02_control_plane/runtime/model_training_stage_receipts/layer_05_alpha_confidence__model_generation__test/receipt.json"],
                        "progress": {"status": "complete"},
                    },
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
    replay_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "replay_execution_runs"
        / "aapl_replay_fixture"
    )
    replay_root.mkdir(parents=True, exist_ok=True)
    replay_receipt_path = replay_root / "replay_execution_receipt.json"
    replay_receipt_path.write_text(
        json.dumps(
            {
                "contract_type": "evaluation_replay_execution_run",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2016-06",
                "target_refs": ["AAPL"],
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
                "replay_result_ref": str(replay_receipt_path),
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


def _write_preview_override(storage_root: Path) -> None:
    path = storage_root / "06_dashboard_cache/config/model_group_promotion_preview_overrides.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_type": "model_group_promotion_preview_overrides",
                "schema_version": 1,
                "status": "enabled",
                "overrides": [
                    {
                        "fold_id": "fold_2016-01_2016-06",
                        "target_symbol": "AAPL",
                        "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2016-06",
                        "decision_status": "baseline_active",
                        "identity": "active",
                        "reason": "Temporary Models-page preview override.",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_unscoped_group_promotion_version(storage_root: Path) -> None:
    replay_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "replay_execution_runs"
        / "unscoped_replay_fixture"
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
        / "model_group_evaluation_unscoped"
        / "fold_settlement_run.json"
    )
    review_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "promotion_review_runs"
        / "model_group_evaluation_unscoped"
    )
    settlement_path.parent.mkdir(parents=True, exist_ok=True)
    review_root.mkdir(parents=True, exist_ok=True)
    settlement_path.write_text(
        json.dumps(
            {
                "contract_type": "fold_settlement_run",
                "replay_result_ref": str(replay_receipt_path),
                "metrics": {
                    "decision_row_count": 80,
                    "feature_diagnostics": {
                        "pca": {"available": True, "points": [{"x": 0.1, "y": 0.2}]},
                        "pcoa": {"available": True, "points": [{"x": 0.2, "y": 0.3}]},
                        "silhouette": {"outcome_label": -0.007, "decision_action": 0.327},
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
                "recommendation": "failed",
                "settlement_run_ref": str(settlement_path),
                "created_at_utc": "2026-05-29T00:07:00Z",
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
                "candidate_model_ref": "storage://trading-manager/model_group/2016-01_2016-06",
                "decision_status": "rejected",
                "settlement_run_ref": str(settlement_path),
                "replay_validation_ref": str(replay_receipt_path),
                "created_at_utc": "2026-05-29T00:07:00Z",
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

    def test_layer_versions_ignore_blocked_partial_task_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            historical = _historical_payload()
            historical["chart_payload"]["task_timeline"].append(
                {
                    "task_uid": "l5-fold2-partial",
                    "month": "2016-fold2",
                    "task_id": "layer_05_alpha_confidence",
                    "task_label": "Layer 5 Alpha Confidence Model",
                    "task_state": "future",
                    "status": "blocked",
                    "stage_type": "model_task",
                    "layer": 5,
                    "status_updated_at_utc": "2026-05-29T00:09:00Z",
                    "detail": {
                        "receipt_refs": [
                            "storage/02_control_plane/runtime/model_training_stage_receipts/layer_05_alpha_confidence__data_acquisition/receipt.json",
                            "storage/02_control_plane/runtime/model_training_stage_receipts/layer_05_alpha_confidence__feature_generation/receipt.json",
                        ],
                        "progress": {"status": "blocked"},
                        "blockers": ["upstream_layer_04_model_generation_complete"],
                    },
                }
            )
            _write_latest(storage_root, "historical_task_progress_summary", historical)
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            payload = build_model_layer_readiness_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:10:00Z")

            layer_five = next(layer for layer in payload["chart_payload"]["layers"] if layer["layer"] == 5)
            self.assertEqual(layer_five["versions"][0]["version_id"], "2016-fold1:model_05_alpha_confidence")

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
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["diagnostic_availability"]["slice_distribution"]["status"], "available")
            variable_diagnostics = payload["chart_payload"]["group_versions"][0]["metrics"]["decision_variable_schema_diagnostics"]
            self.assertEqual(variable_diagnostics["coverage"]["decision_intended_side"]["values"]["long"], 3400)
            self.assertEqual(variable_diagnostics["coverage"]["eval_action_class"]["values"]["taken_good"], 2100)
            scorecards = payload["chart_payload"]["group_versions"][0]["metrics"]["scorecards"]
            self.assertEqual(scorecards["selection_quality"]["taken_good_count"], 2100)
            self.assertFalse(payload["chart_payload"]["group_versions"][0]["metrics"]["evaluation_disagreement_report"]["promotion_gate_basis"]["auroc_is_hard_gate"])

    def test_builds_layer_evaluation_dossiers_with_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_mismatched_group_promotion_version(storage_root)
            _write_preview_override(storage_root)

            payload = build_model_layer_evaluation_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:09:00Z")

            self.assertEqual(payload["contract_type"], MODEL_LAYER_EVALUATION_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_LAYER_EVALUATION_CONTRACT)
            self.assertEqual(len(payload["chart_payload"]["layers"]), 10)
            layer_five = next(row for row in payload["chart_payload"]["layers"] if row["layer"] == 5)
            self.assertEqual(layer_five["evidence_status"], "insufficient_evidence")
            self.assertEqual(layer_five["validity_status"], "insufficient_evidence")
            self.assertIn("After-cost alpha", layer_five["claim"]["target_definition"])
            self.assertIn("ranking_alpha", layer_five["metric_families"])
            self.assertIn("calibrated_prediction", layer_five["metric_families"])
            alpha_binary = next(test for test in layer_five["metric_tests"] if test["metric_id"] == "positive_alpha_auroc_brier_ece")
            self.assertEqual(alpha_binary["role"], "primary")
            self.assertIn("explicit probability", alpha_binary["eligibility"])
            layer_nine = next(row for row in payload["chart_payload"]["layers"] if row["layer"] == 9)
            self.assertIn("option_expression", layer_nine["metric_families"])
            self.assertIn("underlying_only_pnl_as_option_score", {test["metric_id"] for test in layer_nine["metric_tests"] if test["role"] == "avoid"})
            self.assertIn("group_contribution", payload["chart_payload"]["metric_family_descriptions"])
            self.assertTrue(payload["chart_payload"]["model_group_supplemental_tests"])
            predictive = next(section for section in layer_five["sections"] if section["section_id"] == "predictive_evidence")
            self.assertEqual(predictive["status"], "insufficient_evidence")
            self.assertIn("rank_ic_by_horizon", predictive["required_evidence"])
            downstream = next(section for section in layer_five["sections"] if section["section_id"] == "downstream_contribution")
            self.assertEqual(downstream["status"], "reference_only")

    def test_materializes_and_consumes_layer_evaluation_summary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_legacy_layer_evaluation(storage_root)

            artifacts = materialize_layer_evaluation_summary_artifacts(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:10:00Z",
            )
            layer_five_artifact = next(artifact for artifact in artifacts if artifact["layer"] == 5)

            self.assertEqual(layer_five_artifact["contract_type"], LAYER_EVALUATION_SUMMARY_CONTRACT)
            self.assertEqual(layer_five_artifact["evaluation_status"], "evaluated")
            self.assertTrue(layer_five_artifact["source_artifact_refs"])
            self.assertEqual(layer_five_artifact["evaluation_population"]["row_counts"]["model_eval_label"], 2410)
            self.assertIn("minimum_rank_ic", {row["parameter_id"] for row in layer_five_artifact["parameter_values"]})
            self.assertTrue(
                (storage_root / "03_model_artifacts/runtime/model_05_alpha_confidence/layer_evaluation_summary_latest.json").exists()
            )

            payload = build_model_layer_evaluation_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:11:00Z")
            layer_five = next(row for row in payload["chart_payload"]["layers"] if row["layer"] == 5)
            self.assertEqual(layer_five["evidence_status"], "evaluated")
            self.assertEqual(layer_five["validity_status"], "evaluated")
            self.assertEqual(layer_five["evaluation_population"]["row_counts"]["model_eval_label"], 2410)
            predictive = next(section for section in layer_five["sections"] if section["section_id"] == "predictive_evidence")
            self.assertEqual(predictive["status"], "published")
            self.assertIn("minimum_eval_labels", {row["parameter_id"] for row in layer_five["parameter_values"]})
            self.assertEqual(payload["chart_payload"]["artifact_status"]["artifact_count"], 10)

    def test_materializes_local_layer_script_summary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_local_layer_evaluation(storage_root)

            artifacts = materialize_layer_evaluation_summary_artifacts(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:12:00Z",
            )
            layer_five_artifact = next(artifact for artifact in artifacts if artifact["layer"] == 5)

            self.assertEqual(layer_five_artifact["evaluation_status"], "evaluated_local_deferred")
            self.assertEqual(layer_five_artifact["validity_status"], "insufficient_evidence")
            self.assertEqual(layer_five_artifact["evaluation_population"]["row_counts"]["model_rows"], 77837)
            self.assertIn("label_join_coverage_rate", {row["metric_id"] for row in layer_five_artifact["metric_values"]})
            self.assertEqual(layer_five_artifact["parameter_values"], [])
            self.assertIn("runtime_coefficients", {row["coefficient_id"] for row in layer_five_artifact["runtime_coefficients"]})

            payload = build_model_layer_evaluation_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:13:00Z")
            layer_five = next(row for row in payload["chart_payload"]["layers"] if row["layer"] == 5)
            self.assertEqual(layer_five["evidence_status"], "evaluated_local_deferred")
            self.assertEqual(layer_five["validity_status"], "insufficient_evidence")
            self.assertEqual(layer_five["parameter_values"], [])
            self.assertIn("runtime_coefficients", {row["coefficient_id"] for row in layer_five["runtime_coefficients"]})
            predictive = next(section for section in layer_five["sections"] if section["section_id"] == "predictive_evidence")
            self.assertEqual(predictive["status"], "published")

    def test_materializes_runtime_feature_importance_from_model_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_local_layer_evaluation(storage_root)
            _write_runtime_model_artifact(storage_root)

            artifacts = materialize_layer_evaluation_summary_artifacts(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:12:30Z",
            )
            layer_five_artifact = next(artifact for artifact in artifacts if artifact["layer"] == 5)
            coefficient_rows = layer_five_artifact["runtime_coefficients"]

            self.assertIn("3_target_direction_score_10min", {row["label"] for row in coefficient_rows})
            self.assertIn("runtime_feature_importance", {row["role"] for row in coefficient_rows})
            self.assertNotIn("evidence_source", {row.get("coefficient_id") for row in coefficient_rows})

    def test_layer_evaluation_prefers_dated_fold_artifact_over_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_local_layer_evaluation(storage_root)
            fixture_path = storage_root / "03_model_artifacts/runtime/model_05_alpha_confidence/evaluation_summary_fixture.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "layer_number": 5,
                            "model_surface": "model_05_alpha_confidence",
                            "model_id": "model_05_alpha_confidence",
                            "evidence_source": "fixture_generated_model_rows_fixture_outcomes",
                            "model_row_count": 1,
                            "outcome_row_count": 1,
                            "label_row_count": 1,
                            "label_join_coverage_rate": 1.0,
                            "leakage_check_passed": True,
                            "promotion_gate_state": "deferred",
                        },
                        "labels": [{"label_id": "fixture_only"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            artifacts = materialize_layer_evaluation_summary_artifacts(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:14:00Z",
            )
            layer_five_artifact = next(artifact for artifact in artifacts if artifact["layer"] == 5)

            self.assertEqual(layer_five_artifact["evaluation_population"]["row_counts"]["model_rows"], 77837)
            self.assertEqual(
                layer_five_artifact["source_artifact_refs"],
                [str(storage_root / "03_model_artifacts/runtime/model_05_alpha_confidence/evaluation_summary_2016-01.json")],
            )

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

    def test_model_group_versions_allow_explicit_preview_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_mismatched_group_promotion_version(storage_root)
            _write_preview_override(storage_root)

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:07:00Z",
            )

            versions = payload["chart_payload"]["group_versions"]
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["version_label"], "AAPL 2016 fold1")
            self.assertEqual(versions[0]["decision_status"], "baseline_active")
            self.assertEqual(versions[0]["identity"], "active")
            self.assertTrue(versions[0]["preview_override"])
            self.assertEqual(versions[0]["excluded_reason_codes_overridden"], ["replay_scope_target_mismatch"])

    def test_model_group_versions_skip_unscoped_artifacts_and_report_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_unscoped_group_promotion_version(storage_root)

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:08:00Z",
            )

            self.assertEqual(payload["chart_payload"]["group_versions"], [])
            exclusions = payload["chart_payload"]["excluded_group_versions"]
            self.assertEqual(len(exclusions), 1)
            self.assertIn("missing_target_symbol", exclusions[0]["reason_codes"])
            self.assertIn("unscoped_candidate_model_ref", exclusions[0]["reason_codes"])
            self.assertEqual(payload["summary"], "No valid scoped model-group promotion evidence is published.")
            self.assertEqual(payload["issue_refs"][0]["issue_id"], "model_group_promotion_evidence_excluded")

    def test_refresh_materializes_model_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            layer_receipt = refresh_model_layer_readiness_summary_read_model(storage_root=storage_root)
            evaluation_receipt = refresh_model_layer_evaluation_summary_read_model(storage_root=storage_root)
            promotion_receipt = refresh_model_promotion_posture_summary_read_model(storage_root=storage_root)

            self.assertEqual(layer_receipt["refreshed_contract_type"], MODEL_LAYER_READINESS_CONTRACT)
            self.assertEqual(evaluation_receipt["refreshed_contract_type"], MODEL_LAYER_EVALUATION_CONTRACT)
            self.assertEqual(promotion_receipt["refreshed_contract_type"], MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_layer_readiness_summary/latest.json").exists())
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_layer_evaluation_summary/latest.json").exists())
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_promotion_posture_summary/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
