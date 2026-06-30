from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from trading_storage.dashboard_models import (
    MODEL_READINESS_CONTRACT,
    MODEL_PROMOTION_POSTURE_CONTRACT,
    build_model_readiness_summary,
    build_model_promotion_posture_summary,
    refresh_model_readiness_summary_read_model,
    refresh_model_promotion_posture_summary_read_model,
)
from trading_storage.dashboard_replay_review import (
    MODEL_GROUP_REPLAY_REVIEW_CONTRACT,
    build_model_group_replay_review_summary,
    refresh_model_group_replay_review_summary_read_model,
)
from trading_storage.dashboard_read_models import validate_dashboard_read_model


def _write_latest(storage_root: Path, contract_type: str, payload: dict) -> None:
    path = storage_root / "06_dashboard_cache" / "read_models" / f"{contract_type}.json"
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
            "current_month": "2016-01..2017-06",
            "active_task": {"layer": 5},
            "task_timeline": [
                {
                    "task_uid": "m05-train",
                    "month": "2016-01..2017-06",
                    "task_id": "model_05_option_expression.model_generation.train",
                    "task_label": "M05 Option Expression Model",
                    "task_state": "completed",
                    "status": "succeeded",
                    "stage_type": "model_generation",
                    "layer": 5,
                    "status_updated_at_utc": "2026-05-29T00:01:00Z",
                    "detail": {
                        "receipt_refs": ["storage/02_control_plane/runtime/model_training_stage_receipts/model_05_option_expression__model_generation__test/receipt.json"],
                        "progress": {"status": "complete"},
                    },
                },
                {
                    "task_uid": "eval",
                    "month": "2016-01..2017-06",
                    "task_id": "model_group.evaluation",
                    "task_label": "Model Evaluation",
                    "task_state": "current",
                    "status": "ready",
                    "stage_type": "model_evaluation",
                    "status_updated_at_utc": "2026-05-29T00:02:00Z",
                },
                {
                    "task_uid": "promo",
                    "month": "2016-01..2017-06",
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


def _write_target_queue(storage_root: Path, symbols: list[str]) -> None:
    queue_path = storage_root / "02_control_plane" / "runtime" / "model_training_target_queue.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        json.dumps(
            {
                "contract_type": "manager_model_training_target_queue",
                "targets": [
                    {
                        "enabled": True,
                        "symbol": symbol,
                        "training_target_source": "explicit_bootstrap_target",
                    }
                    for symbol in symbols
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_group_promotion_version(storage_root: Path) -> None:
    alpha_artifact_path = (
        storage_root
        / "03_model_artifacts"
        / "runtime"
        / "model_05_alpha_confidence"
        / "after_cost_alpha_model_2016-01_2017-06.json"
    )
    alpha_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_artifact_path.write_text(
        json.dumps(
            {
                "contract_type": "current_replay_entry_utility_model_bundle",
                "training_summary": {
                    "training_mode": "supervised_fit",
                    "sample_count": 128,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
                "replay_execution_run_id": "aapl_replay_fixture",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "target_symbol": "AAPL",
                "target_refs": ["AAPL_CANDIDATE_01", "AAPL_CANDIDATE_02"],
                "candidate_handoff_status": "available",
                "candidate_handoff_source": "fixed_current_snapshot_historical_candidate_universe",
                "candidate_handoff_row_count": 2,
                "candidate_handoff_symbol_count": 2,
                "candidate_handoff_table_ref": "historical_candidate_universe.csv",
                "decision_rows_ref": str(replay_root / "decision_rows.jsonl"),
                "after_cost_alpha_model_ref": str(alpha_artifact_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (replay_root / "decision_rows.jsonl").write_text(
        "\n".join(
            json.dumps(row, sort_keys=True)
            for row in [
                {
                    "timestamp": "2021-01-31T16:00:00-05:00",
                    "entry_threshold_calibration_role": "validation",
                    "realized_return": 0.5,
                    "cost": 0.0,
                },
                {
                    "timestamp": "2021-02-01T16:00:00-05:00",
                    "realized_return": 0.1,
                    "cost": 0.0,
                },
                {
                    "timestamp": "2021-02-02T16:00:00-05:00",
                    "realized_return": -0.2,
                    "cost": 0.0,
                },
                {
                    "timestamp": "2021-02-03T16:00:00-05:00",
                    "realized_return": 0.05,
                    "cost": 0.0,
                },
            ]
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
                "fold_id": "fold_aapl_2016",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "aapl_replay_fixture",
                "target_symbol": "AAPL",
                "replay_result_ref": str(replay_receipt_path),
                "metrics": {
                    "decision_row_count": 5382,
                    "net_return_total": 2.1,
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
                    "benchmark_symbol": "SPY",
                    "benchmark_return_total": 0.11,
                    "benchmark_month_count": 6,
                    "benchmark_beta": 1.23,
                    "market_beta": 1.23,
                    "beta": 1.23,
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
                    "temporal_stability_diagnostics": {
                        "month_slice_count": 6,
                        "slices": [
                            {
                                "month": "2021-02",
                                "net_return_total": -0.05,
                                "benchmark_symbol": "SPY",
                                "benchmark_return_total": 0.02,
                                "spy_return_total": 0.02,
                            }
                        ],
                        "worst_month_return": -0.18,
                        "benchmark_symbol": "SPY",
                        "benchmark_return_total": 0.11,
                        "benchmark_month_count": 6,
                        "benchmark_beta": 1.23,
                        "market_beta": 1.23,
                        "beta": 1.23,
                    },
                    "benchmark_diagnostics": {"status": "available", "benchmark_symbol": "SPY"},
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
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "aapl_replay_fixture",
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
                "fold_id": "fold_aapl_2016",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "aapl_replay_fixture",
                "target_symbol": "AAPL",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
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
    (review_root / "model_group_evaluation_receipt.json").write_text(
        json.dumps(
            {
                "contract_type": "model_group_evaluation_receipt",
                "status": "succeeded",
                "fold_id": "fold_aapl_2016",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "aapl_replay_fixture",
                "target_symbol": "AAPL",
                "fold_settlement_run_ref": str(settlement_path),
                "replay_execution_receipt_ref": str(replay_receipt_path),
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
                "replay_execution_run_id": "crypto_replay_fixture",
                "candidate_model_ref": "storage://trading-manager/model_group/2016-01_2017-06",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "target_symbol": "AAPL",
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
                "fold_id": "fold_aapl_2016",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "crypto_replay_fixture",
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
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "crypto_replay_fixture",
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
                "fold_id": "fold_aapl_2016",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "replay_execution_run_id": "crypto_replay_fixture",
                "target_symbol": "AAPL",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
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


def _write_replay_review_run(storage_root: Path) -> None:
    run_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "post_replay_review_runs"
        / "post_replay_review_20260629T120000Z"
    )
    layer_root = run_root / "layer_attribution"
    layer_root.mkdir(parents=True, exist_ok=True)
    rows_path = run_root / "replay_review_rows.jsonl"
    rows_path.write_text(
        "\n".join(
            json.dumps(row, sort_keys=True)
            for row in [
                {
                    "contract_type": "post_replay_review_row",
                    "review_id": "rr1",
                    "decision_time": "2021-01-19T16:00:00-05:00",
                    "target_symbol": "AAPL",
                    "replay_month": "2021-01",
                    "source_decision_id": "decision-1",
                    "source_decision_index": 1,
                    "candidate_set_scope": "selected_target_selected_option_contract_path",
                    "path_scope": "selected_target:AAPL",
                    "chosen_action": "open_long",
                    "available_action": "open_long",
                    "best_available_action_by_future_outcome": "no_trade",
                    "chosen_action_return": -0.12,
                    "best_available_action_return": 0.0,
                    "regret_to_best_available": 0.12,
                    "cause_family": "model_mechanism_defect",
                    "failure_type": "bad_entry",
                    "first_gap_component": "model_04_unified_decision",
                    "first_gap_mechanism": "overconfident_entry",
                    "miss_attribution_layer": "M04",
                    "impact_normalized_severity_score": 0.42,
                    "review_status": "reviewed",
                },
                {
                    "contract_type": "post_replay_review_row",
                    "review_id": "rr2",
                    "decision_time": "2021-02-01T16:00:00-05:00",
                    "target_symbol": "MSFT",
                    "replay_month": "2021-02",
                    "source_decision_id": "decision-2",
                    "source_decision_index": 2,
                    "candidate_set_scope": "selected_target_selected_option_contract_path",
                    "path_scope": "selected_target:MSFT",
                    "chosen_action": "open_long",
                    "best_available_action_by_future_outcome": "open_long",
                    "chosen_action_return": 0.08,
                    "best_available_action_return": 0.08,
                    "regret_to_best_available": 0.0,
                    "cause_family": "not_failed",
                    "failure_type": "none",
                    "first_gap_component": "none",
                    "miss_attribution_layer": "none",
                    "impact_normalized_severity_score": 0.0,
                    "review_status": "reviewed",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    decision_rows_path = run_root / "decision_rows.jsonl"
    decision_rows_path.write_text(
        "\n".join(
            json.dumps(row, sort_keys=True)
            for row in [
                {
                    "contract_type": "evaluation_replay_decision_row",
                    "decision_id": "decision-1",
                    "timestamp": "2021-01-19T16:00:00-05:00",
                    "target_ref": "AAPL",
                    "replay_month": "2021-01",
                    "path_scope": "selected_target:AAPL",
                    "decision_action": "open_long",
                    "fill_status": "simulated_filled",
                    "decision_status": "accepted",
                    "baseline_return": 0.0,
                    "realized_return": -0.12,
                    "directional_underlying_return": -0.08,
                    "outcome_label": 0,
                    "model_layer_refs": {
                        "model_01_background_context": "m01-ref-1",
                        "model_02_target_state": "m02-ref-1",
                        "model_03_event_state": "m03-ref-1",
                        "model_04_unified_decision": "m04-ref-1",
                        "model_05_option_expression": "m05-ref-1",
                    },
                    "model_layer_diagnostics": {
                        "model_01_background_context": {"state_quality_score": 0.7, "market_risk_stress_score": 0.4},
                        "model_02_target_state": {"target_ref": "AAPL", "target_direction_score_1D": 0.8, "tradability_score_1D": 0.9},
                        "model_03_event_state": {"event_uncertainty_score_1D": 0.0, "event_entry_block_pressure_score_1D": 0.0},
                        "model_04_unified_decision": {"resolved_underlying_action_type": "open_long"},
                        "model_05_option_expression": {"selected_expression_type": "long_call", "selected_contract_ref": "AAPL_2021-01-22_C_130"},
                    },
                },
                {
                    "contract_type": "evaluation_replay_decision_row",
                    "decision_id": "decision-2",
                    "timestamp": "2021-02-01T16:00:00-05:00",
                    "target_ref": "MSFT",
                    "replay_month": "2021-02",
                    "path_scope": "selected_target:MSFT",
                    "decision_action": "open_long",
                    "fill_status": "simulated_filled",
                    "decision_status": "accepted",
                    "baseline_return": 0.0,
                    "realized_return": 0.08,
                    "directional_underlying_return": 0.04,
                    "outcome_label": 1,
                    "model_layer_refs": {
                        "model_01_background_context": "m01-ref-2",
                        "model_02_target_state": "m02-ref-2",
                        "model_03_event_state": "m03-ref-2",
                        "model_04_unified_decision": "m04-ref-2",
                        "model_05_option_expression": "m05-ref-2",
                    },
                    "model_layer_diagnostics": {
                        "model_01_background_context": {"state_quality_score": 0.8, "market_risk_stress_score": 0.3},
                        "model_02_target_state": {"target_ref": "MSFT", "target_direction_score_1D": 0.7, "tradability_score_1D": 0.8},
                        "model_03_event_state": {"event_uncertainty_score_1D": 0.1, "event_entry_block_pressure_score_1D": 0.0},
                        "model_04_unified_decision": {"resolved_underlying_action_type": "open_long"},
                        "model_05_option_expression": {"selected_expression_type": "long_call", "selected_contract_ref": "MSFT_2021-02-05_C_240"},
                    },
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    layer_rows_path = run_root / "replay_layer_decision_review_rows.jsonl"
    layer_rows: list[dict[str, object]] = []
    layer_labels = {
        "model_01_background_context": "M01 Background Context",
        "model_02_target_state": "M02 Target State",
        "model_03_event_state": "M03 Event State",
        "model_04_unified_decision": "M04 Unified Decision",
        "model_05_option_expression": "M05 Option Expression",
    }
    for decision_index, decision_id in enumerate(("decision-1", "decision-2"), start=1):
        for layer_order, (layer_id, layer_label) in enumerate(layer_labels.items(), start=1):
            incorrect = decision_id == "decision-1" and layer_id in {
                "model_04_unified_decision",
                "model_05_option_expression",
            }
            layer_rows.append(
                {
                    "contract_type": "post_replay_layer_decision_review_row",
                    "review_id": f"layer-{decision_index}-{layer_order}",
                    "decision_time": "2021-01-19T16:00:00-05:00"
                    if decision_id == "decision-1"
                    else "2021-02-01T16:00:00-05:00",
                    "target_symbol": "AAPL" if decision_id == "decision-1" else "MSFT",
                    "replay_month": "2021-01" if decision_id == "decision-1" else "2021-02",
                    "source_decision_id": decision_id,
                    "source_decision_index": decision_index,
                    "layer_id": layer_id,
                    "layer_label": layer_label,
                    "layer_order": layer_order,
                    "candidate_set_scope": "selected_path_current_decision_set",
                    "path_scope": f"selected_target:{'AAPL' if decision_id == 'decision-1' else 'MSFT'}",
                    "effective_decision": f"{layer_id}:{decision_id}",
                    "effective_decision_status": "measured",
                    "chosen_action": "open_long",
                    "available_action": ["open_long", "baseline_action"],
                    "best_available_action_by_future_outcome": "baseline_action" if incorrect else "open_long",
                    "chosen_action_return": -0.08 if incorrect else 0.04,
                    "best_available_action_return": 0.0 if incorrect else 0.04,
                    "correctness_class": "incorrect" if incorrect else "correct",
                    "acceptability_class": "unacceptable" if incorrect else "acceptable",
                    "scoring_status": "scored_post_replay_outcome_label"
                    if layer_id in {"model_04_unified_decision", "model_05_option_expression"}
                    else "scored_point_in_time_diagnostic",
                    "regret_to_best_available": 0.08 if incorrect else 0.0,
                    "impact_normalized_severity_score": 0.08 if incorrect else 0.0,
                    "cause_family": "model_mechanism_defect" if incorrect else "not_attributed",
                    "failure_type": "layer_failure" if incorrect else "none",
                    "first_gap_component": layer_id if incorrect else "no_gap",
                    "first_gap_mechanism": "fixture_gap" if incorrect else "no_gap",
                    "outcome_label": 0 if decision_id == "decision-1" else 1,
                    "classification_basis": "fixture_published_layer_review",
                    "hindsight_caution": "Future returns are labels for review; they are not decision-time inputs.",
                }
            )
    layer_rows_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in layer_rows) + "\n",
        encoding="utf-8",
    )
    (run_root / "post_replay_review_receipt.json").write_text(
        json.dumps(
            {
                "contract_type": "post_replay_review_receipt",
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "target_symbol": "AAPL",
                "replay_execution_run_id": "model_group_replay_fold_aapl_2016_20260629T120000Z",
                "created_at_utc": "2026-06-29T12:00:00Z",
                "completed_at_utc": "2026-06-29T12:01:00Z",
                "processed_review_count": 2,
                "expected_review_count": 2,
                "event_candidate_count": 1,
                "review_rows_ref": str(rows_path),
                "layer_review_rows_ref": str(layer_rows_path),
                "decision_rows_ref": str(decision_rows_path),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "replay_review_performance_summary.json").write_text(
        json.dumps(
            {
                "contract_type": "model_group_replay_review_performance_summary",
                "decision_scope": {
                    "decision_row_count": 2,
                    "filled_count": 2,
                    "selected_target_count": 2,
                    "selected_timestamp_count": 2,
                    "decision_status_counts": {"accepted": 2},
                    "fill_status_counts": {"simulated_filled": 2},
                    "selected_timestamp_counts": {"2021-01-19T16:00:00-05:00": 1},
                },
                "target_performance": {"gross_pnl_total": -10.0, "positive_return_count": 1, "negative_return_count": 1},
                "stock_selection": {"selected_top_10_count": 2, "selected_outside_top_25_count": 0},
                "direction_expression": {"aligned_option_expression_count": 2, "mismatched_option_expression_count": 0},
                "option_expression": {"path_status_counts": {"available": 2}},
                "replacement_review": {"replacement_triggered_count": 1, "blocked_replacements_sample": [{"target_ref": "AAPL"}]},
                "layer_differentiation": {
                    "model_01_background_context": {"row_count": 2, "varying_scalar_keys": ["model_ref"]},
                    "model_02_target_state": {"row_count": 2, "varying_scalar_keys": ["target_ref"]},
                    "model_03_event_state": {"row_count": 2, "varying_scalar_keys": ["model_ref"]},
                    "model_04_unified_decision": {"row_count": 2, "varying_scalar_keys": ["dominant_horizon"]},
                    "model_05_option_expression": {"row_count": 2, "varying_scalar_keys": ["selected_contract_ref"]},
                    "model_06_residual_event_governance": {"row_count": 2, "varying_scalar_keys": ["event_risk_intervention_ref"]},
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (layer_root / "parameter_replay_review_report.json").write_text(
        json.dumps(
            {
                "contract_type": "model_group_parameter_replay_review_report",
                "summary": {
                    "parameter_count": 3,
                    "classification_counts": {"directionally_useful": 1, "suspect_requires_redesign": 1},
                    "directionally_useful_parameters": ["feature_momentum_7d"],
                    "suspect_requires_redesign_parameters": ["feature_volume_rank_30d"],
                    "interpretation_limits": ["Replay diagnostics are not causal feature attribution."],
                    "fixed_input_only": True,
                    "threshold_selection_performed": False,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (layer_root / "operation_component_flow.csv").write_text(
        "\n".join(
            [
                "component_index,operation_component_id,runtime_component_ref,operation_component_label,operation_role,applicability_status,input_count,output_count,dropped_or_blocked_count,censored_count,settled_metric_eligible_count,settled_metric_excluded_count,first_limiting_projection_count,first_limiting_projections,review_projection_refs,outcome_metric_available,mean_prediction_score,score_label_spearman,score_return_spearman,mean_realized_return,hit_rate,tail_loss_count,stage_verdict,verdict_basis,threshold_selection_performed,retraining_performed,fixed_input_only",
                "1,C01_intake_operation,component_01_intake,C01 Intake,prepare inputs,candidate_entry_path,2,2,0,0,2,0,0,,background_context;target_state,True,0.81,0.2,0.3,0.02,0.5,1,neutral_measured,no_prior_observable_bad_rate,False,False,True",
                "3,C03_lifecycle_operation,component_03_lifecycle,C03 Lifecycle,manage positions,not_applicable_for_candidate_entry_replay,0,0,0,0,0,0,0,,,False,,,,,,0,not_applicable,candidate_entry_replay_does_not_operate_lifecycle_component,False,False,True",
                "7,C07_failure_review_operation,component_07_failure_review,C07 Failure Review,review settled failures,candidate_entry_path,2,2,0,0,2,0,2,settled_prediction_quality,residual_event_governance;settled_prediction_quality,True,0.81,0.2,0.3,0.02,0.5,1,first_observed_deterioration,settled_survivor_cohort_bad_rate_above_half,False,False,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (layer_root / "operation_component_review_packet.csv").write_text(
        "\n".join(
            [
                "component_index,operation_component_id,runtime_component_ref,operation_component_label,operation_role,applicability_status,input_count,output_count,dropped_or_blocked_count,settled_metric_eligible_count,survival_verdict,survival_verdict_basis,review_projections,internal_review_refs,missing_review_outputs,metric_effectiveness_status,metric_effectiveness_flags,first_limiting_projection_count,can_assign_operation_fault,interpretation_status,threshold_selection_performed,retraining_performed,fixed_input_only",
                "1,C01_intake_operation,component_01_intake,C01 Intake,prepare inputs,candidate_entry_path,2,2,0,2,neutral_measured,no_prior_observable_bad_rate,background_context;target_state,operation_component_metrics.csv,,effectiveness_metrics_reviewed,,0,False,reviewable_no_problem_observed,False,False,True",
                "3,C03_lifecycle_operation,component_03_lifecycle,C03 Lifecycle,manage positions,not_applicable_for_candidate_entry_replay,0,0,0,0,not_applicable,candidate_entry_replay_does_not_operate_lifecycle_component,,operation_component_metrics.csv,,effectiveness_metrics_not_available,,0,False,not_applicable_for_candidate_entry_replay,False,False,True",
                "7,C07_failure_review_operation,component_07_failure_review,C07 Failure Review,review settled failures,candidate_entry_path,2,2,0,2,first_observed_deterioration,settled_survivor_cohort_bad_rate_above_half,residual_event_governance;settled_prediction_quality,operation_component_metrics.csv,,effectiveness_metrics_reviewed,,2,False,problem_observed_at_failure_review_not_causal_operation_fault,False,False,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (layer_root / "operation_component_metrics.csv").write_text(
        "\n".join(
            [
                "component_index,operation_component_id,runtime_component_ref,operation_component_label,metric_family,metric_name,metric_scope,availability_status,reason_codes,point_in_time_input_fields,future_outcome_fields,row_count,eligible_row_count,selected_count,universe_count_mean,selected_target_present_count,selected_forward_return_mean,selected_forward_return_rank_mean,selected_forward_return_percentile_mean,top_quartile_hit_rate,opportunity_cost_to_best_mean,opportunity_cost_to_median_mean,value,diagnostic_only,threshold_selection_performed,retraining_performed,fixed_input_only",
                "1,C01_intake_operation,component_01_intake,C01 Intake,model_candidate_discovery,visible_candidate_model_scoring_coverage,point_in_time_model_candidate_trace,computed,,visible_candidate;model_score_available,,2,2,2,10,2,0.02,1.5,0.7,0.5,0.03,0.01,1.0,True,False,False,True",
                "3,C03_lifecycle_operation,component_03_lifecycle,C03 Lifecycle,position_lifecycle_quality,existing_position_lifecycle_outcome,candidate_entry_replay,not_applicable,candidate_entry_replay_does_not_operate_lifecycle_component,,,0,0,0,,0,,,,,,,,True,False,False,True",
                "7,C07_failure_review_operation,component_07_failure_review,C07 Failure Review,settled_failure_review_quality,settled_score_outcome_surface,settled_replay_rows,computed,,prediction_score;model_evidence_chain,outcome_label;realized_return,2,2,2,,0,0.02,,,0.5,,,0.2,True,False,False,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_residual_event_run(storage_root: Path) -> None:
    run_root = (
        storage_root
        / "05_replay_datasets"
        / "promotion_replay_candidate_policy"
        / "post_replay_attribution_runs"
        / "post_replay_residual_event_governance_20260629T120500Z"
    )
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "post_replay_attribution_receipt.json").write_text(
        json.dumps(
            {
                "contract_type": "post_replay_residual_event_governance_receipt",
                "status": "succeeded",
                "run_id": run_root.name,
                "candidate_model_ref": "storage://trading-manager/model_group/aapl/2016-01_2017-06",
                "candidate_fold_id": "fold_aapl_2016",
                "candidate_training_target": "AAPL",
                "target_symbol": "AAPL",
                "replay_execution_run_id": "model_group_replay_fold_aapl_2016_20260629T120000Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "event_focus_proposals.jsonl").write_text(
        json.dumps(
            {
                "contract_type": "model_06_residual_event_governance_event_focus_proposal",
                "event_focus_proposal_id": "event_focus_1",
                "event_ref": "event_1",
                "event_summary": "Market holiday affected the replay decision window.",
                "target_symbol": "AAPL",
                "failure_type": "bad_entry",
                "proposal_status": "pending_review",
                "review_gate": "requires_event_strategy_promotion_review",
                "supporting_failure_count": 1,
                "average_attribution_confidence_score": 0.65,
                "average_impact_magnitude_abs_return": 0.12,
                "source_replay_review_ids": ["rr1"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "residual_event_governance_rows.jsonl").write_text(
        json.dumps(
            {
                "contract_type": "model_06_residual_event_governance_event_attribution_row",
                "attribution_id": "attr_1",
                "attribution_status": "attributed",
                "target_symbol": "AAPL",
                "failure_type": "bad_entry",
                "impact_scope_type": "target_window",
                "dominant_event_candidate": "event_1",
                "source_replay_review_id": "rr1",
                "attribution_confidence_score": 0.65,
            },
            sort_keys=True,
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
                "candidate_model_ref": "storage://trading-manager/model_group/2016-01_2017-06",
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
                "fold_id": "fold_aapl_2016",
                "candidate_model_ref": "storage://trading-manager/model_group/2016-01_2017-06",
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
    def test_builds_model_readiness_from_existing_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)

            payload = build_model_readiness_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["contract_type"], MODEL_READINESS_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_READINESS_CONTRACT)
            layers = payload["chart_payload"]["layers"]
            self.assertEqual(len(layers), 6)
            layer_five = next(layer for layer in layers if layer["layer"] == 5)
            self.assertEqual(layer_five["versions"][0]["version_id"], "2016-01..2017-06:model_05_option_expression")
            self.assertEqual(layer_five["promotion"]["status"], "deferred")
            self.assertEqual(len(payload["chart_payload"]["group_versions"]), 1)

    def test_layer_versions_ignore_blocked_partial_task_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            historical = _historical_payload()
            historical["chart_payload"]["task_timeline"].append(
                {
                    "task_uid": "l5-fold2-partial",
                    "month": "2017-01..2018-06",
                    "task_id": "model_05_option_expression",
                    "task_label": "M05 Option Expression Model",
                    "task_state": "future",
                    "status": "blocked",
                    "stage_type": "model_task",
                    "layer": 5,
                    "status_updated_at_utc": "2026-05-29T00:09:00Z",
                    "detail": {
                        "receipt_refs": [
                            "storage/02_control_plane/runtime/model_training_stage_receipts/model_05_option_expression__data_acquisition/receipt.json",
                            "storage/02_control_plane/runtime/model_training_stage_receipts/model_05_option_expression__feature_generation/receipt.json",
                        ],
                        "progress": {"status": "blocked"},
                        "blockers": ["upstream_model_03_generation_complete"],
                    },
                }
            )
            _write_latest(storage_root, "historical_task_progress_summary", historical)
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            payload = build_model_readiness_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:10:00Z")

            layer_five = next(layer for layer in payload["chart_payload"]["layers"] if layer["layer"] == 5)
            self.assertEqual(layer_five["versions"][0]["version_id"], "2016-01..2017-06:model_05_option_expression")

    def test_builds_model_promotion_posture_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)

            payload = build_model_promotion_posture_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["contract_type"], MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertEqual(validate_dashboard_read_model(payload), MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertEqual(len(payload["chart_payload"]["models"]), 1)
            layer_five = next(row for row in payload["chart_payload"]["models"] if row["layer"] == 5)
            self.assertEqual(layer_five["version_id"], "2016-01..2017-06:model_05_option_expression")
            self.assertEqual(layer_five["evaluation_status"], "ready")
            self.assertEqual(payload["chart_payload"]["status_counts"], {"deferred": 1})
            self.assertEqual(payload["chart_payload"]["identity_counts"], {"retired": 1})
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["version_label"], "AAPL 2016")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["candidate_fold_id"], "fold_aapl_2016")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["candidate_training_target"], "AAPL")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["replay_execution_run_id"], "aapl_replay_fixture")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["net_return_total"], 2.1)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["auroc"], 0.5246)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["pr_auc"], 0.61)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["beta"], 1.23)
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["benchmark_symbol"], "SPY")
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["metrics"]["benchmark_return_total"], 0.11)
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
            temporal = payload["chart_payload"]["group_versions"][0]["metrics"]["temporal_stability_diagnostics"]
            self.assertEqual(temporal["beta"], 1.23)
            self.assertEqual(temporal["slices"][0]["spy_return_total"], 0.02)
            self.assertEqual(
                temporal["slices"][0]["net_return_path_ohlc"],
                {"open": 1.0, "high": 1.1, "low": 0.9, "close": 0.95},
            )

    def test_model_group_versions_wait_for_public_evaluation_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            historical = _historical_payload()
            for task in historical["chart_payload"]["task_timeline"]:
                if str(task.get("task_id", "")).startswith("model_group."):
                    task["task_state"] = "future"
            _write_latest(storage_root, "historical_task_progress_summary", historical)
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)

            payload = build_model_promotion_posture_summary(storage_root=storage_root, generated_at_utc="2026-05-29T00:04:00Z")

            self.assertEqual(payload["chart_payload"]["group_versions"], [])
            self.assertEqual(payload["chart_payload"]["excluded_group_versions"], [])

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
            self.assertEqual(payload["chart_payload"]["group_versions"][0]["version_label"], "AAPL 2016")

    def test_model_group_versions_skip_stale_date_range_fold_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)
            decision_path = (
                storage_root
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "promotion_review_runs"
                / "model_group_evaluation_fixture"
                / "promotion_eligibility_decision.json"
            )
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            decision["candidate_fold_id"] = "fold_2016-01_2016-06"
            decision["fold_id"] = "fold_2016-01_2016-06"
            decision_path.write_text(json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8")

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:04:00Z",
            )

            self.assertEqual(payload["chart_payload"]["group_versions"], [])
            self.assertIn("stale_replay_fold_id", payload["chart_payload"]["excluded_group_versions"][0]["reason_codes"])

    def test_model_group_versions_skip_replay_without_candidate_handoff(self) -> None:
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
            self.assertIn("replay_candidate_handoff_missing", payload["chart_payload"]["excluded_group_versions"][0]["reason_codes"])

    def test_model_group_versions_skip_targets_outside_explicit_training_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_target_queue(storage_root, ["MSFT"])
            _write_group_promotion_version(storage_root)

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:07:00Z",
            )

            self.assertEqual(payload["chart_payload"]["group_versions"], [])
            exclusions = payload["chart_payload"]["excluded_group_versions"]
            self.assertEqual(len(exclusions), 1)
            self.assertIn("target_not_in_training_queue", exclusions[0]["reason_codes"])

    def test_model_group_versions_skip_no_supervised_fit_alpha_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())
            _write_group_promotion_version(storage_root)
            alpha_artifact_path = (
                storage_root
                / "03_model_artifacts"
                / "runtime"
                / "model_05_alpha_confidence"
                / "after_cost_alpha_model_2016-01_2017-06.json"
            )
            alpha_artifact_path.write_text(
                json.dumps(
                    {
                        "contract_type": "current_replay_entry_utility_model_bundle",
                        "training_summary": {
                            "training_mode": "policy_bundle_no_supervised_fit",
                            "sample_count": None,
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_model_promotion_posture_summary(
                storage_root=storage_root,
                generated_at_utc="2026-05-29T00:07:30Z",
            )

            self.assertEqual(payload["chart_payload"]["group_versions"], [])
            exclusions = payload["chart_payload"]["excluded_group_versions"]
            self.assertEqual(len(exclusions), 1)
            self.assertIn("after_cost_alpha_model_not_trained", exclusions[0]["reason_codes"])

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
            self.assertIn("missing_candidate_training_target", exclusions[0]["reason_codes"])
            self.assertIn("missing_replay_execution_run_id", exclusions[0]["reason_codes"])
            self.assertIn("unscoped_candidate_model_ref", exclusions[0]["reason_codes"])
            self.assertEqual(payload["summary"], "No valid scoped model-group promotion evidence is published.")
            self.assertEqual(payload["issue_refs"][0]["issue_id"], "model_group_promotion_evidence_excluded")

    def test_refresh_materializes_model_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_latest(storage_root, "historical_task_progress_summary", _historical_payload())
            _write_latest(storage_root, "execution_realtime_trading_runtime_status", _runtime_payload())

            layer_receipt = refresh_model_readiness_summary_read_model(storage_root=storage_root)
            promotion_receipt = refresh_model_promotion_posture_summary_read_model(storage_root=storage_root)

            self.assertEqual(layer_receipt["refreshed_contract_type"], MODEL_READINESS_CONTRACT)
            self.assertEqual(promotion_receipt["refreshed_contract_type"], MODEL_PROMOTION_POSTURE_CONTRACT)
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_readiness_summary.json").exists())
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_promotion_posture_summary.json").exists())

    def test_replay_review_summary_projects_review_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_replay_review_run(storage_root)
            _write_residual_event_run(storage_root)

            payload = build_model_group_replay_review_summary(
                storage_root=storage_root,
                generated_at_utc="2026-06-29T12:10:00Z",
            )

            self.assertEqual(payload["contract_type"], MODEL_GROUP_REPLAY_REVIEW_CONTRACT)
            validate_dashboard_read_model(payload, expected_contract_type=MODEL_GROUP_REPLAY_REVIEW_CONTRACT)
            chart = payload["chart_payload"]
            self.assertEqual(len(chart["review_runs"]), 1)
            self.assertNotIn("event_runs", chart)
            self.assertNotIn("page_contracts", chart)
            review = chart["review_runs"][0]
            self.assertEqual(review["decision_review"]["row_count"], 2)
            self.assertEqual(review["decision_review"]["cause_family_counts"]["model_mechanism_defect"], 1)
            self.assertEqual(review["parameter_review"]["classification_counts"]["directionally_useful"], 1)
            self.assertEqual(review["performance"]["decision_scope"]["decision_row_count"], 2)
            self.assertNotIn("selected_timestamp_counts", review["performance"]["decision_scope"])
            replay_decisions = review["replay_decisions_m01_m05"]
            self.assertEqual([layer["layer_id"] for layer in replay_decisions["included_layers"]], [
                "model_01_background_context",
                "model_02_target_state",
                "model_03_event_state",
                "model_04_unified_decision",
                "model_05_option_expression",
            ])
            self.assertEqual(replay_decisions["excluded_layers"][0]["layer_id"], "model_06_residual_event_governance")
            self.assertEqual(replay_decisions["detail_row_count"], 10)
            self.assertEqual(replay_decisions["layer_quality_summary"]["model_01_background_context"]["effective_decision_count"], 2)
            self.assertEqual(
                replay_decisions["layer_quality_summary"]["model_01_background_context"]["evidence_status"],
                "published",
            )
            self.assertEqual(replay_decisions["layer_quality_summary"]["model_01_background_context"]["scored_decision_count"], 2)
            self.assertEqual(replay_decisions["layer_quality_summary"]["model_04_unified_decision"]["effective_decision_count"], 2)
            self.assertEqual(replay_decisions["layer_quality_summary"]["model_04_unified_decision"]["incorrect_count"], 1)
            self.assertEqual(replay_decisions["layer_quality_summary"]["model_05_option_expression"]["effective_decision_count"], 2)
            self.assertEqual(replay_decisions["layer_decision_rows"][0]["layer_id"], "model_01_background_context")
            self.assertEqual(replay_decisions["layer_decision_rows"][0]["scoring_status"], "scored_point_in_time_diagnostic")
            m04_rows = [row for row in replay_decisions["layer_decision_rows"] if row["layer_id"] == "model_04_unified_decision"]
            self.assertEqual(m04_rows[0]["correctness_class"], "incorrect")
            self.assertEqual(m04_rows[1]["correctness_class"], "correct")
            self.assertNotIn("model_06_residual_event_governance", replay_decisions["layer_quality_summary"])
            replay_operations = review["replay_operations_c01_c07"]
            self.assertEqual(replay_operations["status"], "ready")
            self.assertEqual(
                [component["component_id"] for component in replay_operations["included_components"]],
                [
                    "component_01_intake",
                    "component_02_entry",
                    "component_03_lifecycle",
                    "component_04_option_review",
                    "component_05_order_intent",
                    "component_06_execution_gate",
                    "component_07_failure_review",
                ],
            )
            c01 = replay_operations["component_summary"]["component_01_intake"]
            self.assertEqual(c01["input_count"], 2)
            self.assertEqual(c01["dropped_or_blocked_count"], 0)
            self.assertEqual(c01["computed_metric_count"], 1)
            c03 = replay_operations["component_summary"]["component_03_lifecycle"]
            self.assertEqual(c03["applicability_status"], "not_applicable_for_candidate_entry_replay")
            self.assertEqual(c03["input_count"], 0)
            self.assertEqual(c03["not_applicable_metric_count"], 1)
            c07 = replay_operations["component_summary"]["component_07_failure_review"]
            self.assertEqual(c07["first_limiting_projection_count"], 2)
            self.assertEqual(c07["stage_verdict"], "first_observed_deterioration")
            self.assertEqual(replay_operations["detail_row_count"], 3)
            self.assertEqual(replay_operations["component_metric_rows"][0]["component_id"], "component_01_intake")

    def test_replay_review_summary_keeps_latest_review_run_per_current_fold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_replay_review_run(storage_root)
            review_root = (
                storage_root
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "post_replay_review_runs"
            )
            older_run = review_root / "post_replay_review_20260629T120000Z"
            newer_run = review_root / "post_replay_review_20260629T121500Z"
            shutil.copytree(older_run, newer_run)
            receipt_path = newer_run / "post_replay_review_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["replay_execution_run_id"] = "model_group_replay_fold_aapl_2016_20260629T121400Z"
            receipt["created_at_utc"] = "2026-06-29T12:15:00Z"
            receipt["completed_at_utc"] = "2026-06-29T12:16:00Z"
            receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
            performance_path = newer_run / "replay_review_performance_summary.json"
            performance = json.loads(performance_path.read_text(encoding="utf-8"))
            performance["decision_scope"]["decision_row_count"] = 3
            performance["decision_scope"]["filled_count"] = 3
            performance["target_performance"]["gross_pnl_total"] = 25.0
            performance_path.write_text(json.dumps(performance, sort_keys=True) + "\n", encoding="utf-8")

            payload = build_model_group_replay_review_summary(
                storage_root=storage_root,
                generated_at_utc="2026-06-29T12:20:00Z",
            )

            runs = payload["chart_payload"]["review_runs"]
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["review_run_id"], "post_replay_review_20260629T121500Z")
            self.assertEqual(runs[0]["replay_execution_run_id"], "model_group_replay_fold_aapl_2016_20260629T121400Z")
            self.assertEqual(runs[0]["performance"]["decision_scope"]["decision_row_count"], 3)
            self.assertEqual(payload["lineage_refs"][0]["candidate_run_count"], 2)
            self.assertEqual(payload["lineage_refs"][0]["superseded_review_run_count"], 1)

    def test_replay_review_summary_skips_stale_date_range_replay_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_replay_review_run(storage_root)
            _write_residual_event_run(storage_root)
            review_receipt = (
                storage_root
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "post_replay_review_runs"
                / "post_replay_review_20260629T120000Z"
                / "post_replay_review_receipt.json"
            )
            review_payload = json.loads(review_receipt.read_text(encoding="utf-8"))
            review_payload["candidate_fold_id"] = "fold_2016-01_2016-06"
            review_receipt.write_text(json.dumps(review_payload, sort_keys=True) + "\n", encoding="utf-8")
            event_receipt = (
                storage_root
                / "05_replay_datasets"
                / "promotion_replay_candidate_policy"
                / "post_replay_attribution_runs"
                / "post_replay_residual_event_governance_20260629T120500Z"
                / "post_replay_attribution_receipt.json"
            )
            event_payload = json.loads(event_receipt.read_text(encoding="utf-8"))
            event_payload["candidate_fold_id"] = "fold_2016-01_2016-06"
            event_receipt.write_text(json.dumps(event_payload, sort_keys=True) + "\n", encoding="utf-8")

            payload = build_model_group_replay_review_summary(
                storage_root=storage_root,
                generated_at_utc="2026-06-29T12:10:00Z",
            )

            self.assertEqual(payload["status"], "not_reported")
            self.assertEqual(payload["chart_payload"]["review_runs"], [])
            self.assertNotIn("event_runs", payload["chart_payload"])

    def test_refresh_materializes_replay_review_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = Path(tmp)
            _write_replay_review_run(storage_root)

            receipt = refresh_model_group_replay_review_summary_read_model(storage_root=storage_root)

            self.assertEqual(receipt["refreshed_contract_type"], MODEL_GROUP_REPLAY_REVIEW_CONTRACT)
            self.assertTrue((storage_root / "06_dashboard_cache/read_models/model_group_replay_review_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
