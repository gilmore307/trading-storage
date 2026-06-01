"""Models page dashboard read-model producers.

These producers expose model lifecycle posture from already-materialized
dashboard summaries. They do not query raw model internals, activate models,
submit broker work, or mutate lifecycle state.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .artifact_store import now_utc
from .dashboard_read_models import _write_atomic_json
from .dashboard_read_models import materialize_dashboard_read_model

LAYER_EVALUATION_SUMMARY_CONTRACT = "layer_evaluation_summary"
MODEL_LAYER_READINESS_CONTRACT = "model_layer_readiness_summary"
MODEL_LAYER_EVALUATION_CONTRACT = "model_layer_evaluation_summary"
MODEL_PROMOTION_POSTURE_CONTRACT = "model_promotion_posture_summary"
LAYER_EVALUATION_SUMMARY_SCHEMA_REF = f"storage/03_model_artifacts/schemas/{LAYER_EVALUATION_SUMMARY_CONTRACT}.schema.json"
MODEL_LAYER_READINESS_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_LAYER_READINESS_CONTRACT}.schema.json"
MODEL_LAYER_EVALUATION_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_LAYER_EVALUATION_CONTRACT}.schema.json"
MODEL_PROMOTION_POSTURE_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_PROMOTION_POSTURE_CONTRACT}.schema.json"

HISTORICAL_TASK_PROGRESS_CONTRACT = "historical_task_progress_summary"
EXECUTION_RUNTIME_STATUS_CONTRACT = "execution_realtime_trading_runtime_status"
DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_STALE_AFTER_SECONDS = 900
MODEL_GROUP_PROMOTION_PREVIEW_OVERRIDE_PATH = Path("06_dashboard_cache/config/model_group_promotion_preview_overrides.json")
LAYER_EVALUATION_ARTIFACT_DIR = Path("03_model_artifacts/runtime")
RUNTIME_COEFFICIENT_PAYLOAD_KEYS = (
    "runtime_coefficients",
    "scoring_coefficients",
    "model_coefficients",
    "feature_coefficients",
    "factor_coefficients",
    "coefficient_values",
    "feature_importance",
    "feature_importances",
    "factor_weights",
    "scoring_weights",
    "row_contributions",
    "scoring_contributions",
    "feature_contributions",
)

MODEL_LAYERS = (
    (1, "model_01_market_regime", "Market Regime"),
    (2, "model_02_sector_context", "Sector Context"),
    (3, "model_03_target_state_vector", "Target State Vector"),
    (4, "model_04_event_failure_risk", "Event Failure Risk"),
    (5, "model_05_alpha_confidence", "Alpha Confidence"),
    (6, "model_06_dynamic_risk_policy", "Dynamic Risk Policy"),
    (7, "model_07_position_projection", "Position Projection"),
    (8, "model_08_underlying_action", "Underlying Action"),
    (9, "model_09_option_expression", "Option Expression"),
    (10, "model_10_event_risk_governor", "Event Risk Governor"),
)

LAYER_EVALUATION_CLAIMS = {
    1: {
        "claim": "Market regime state is separable, stable, and useful as upstream context.",
        "target_definition": "Broad market regime/context state, not a direct trade label.",
        "required_metrics": ["state_separability", "regime_stability", "drift", "downstream_contribution"],
    },
    2: {
        "claim": "Sector and proxy context adds stable relative information beyond market regime.",
        "target_definition": "Sector/proxy-relative context state.",
        "required_metrics": ["relative_context_accuracy", "proxy_stability", "sector_slice_robustness", "downstream_contribution"],
    },
    3: {
        "claim": "Target state vectors are point-in-time, non-leaky, and reconstruct useful target context.",
        "target_definition": "Target-specific state representation for downstream alpha/risk layers.",
        "required_metrics": ["state_reconstruction", "missingness", "point_in_time_leakage", "state_drift"],
    },
    4: {
        "claim": "Known event-failure risk is represented before alpha/action scoring.",
        "target_definition": "Pre-known event risk state, separate from post-replay residual attribution.",
        "required_metrics": ["event_risk_precision", "event_risk_recall", "duplicate_event_resistance", "event_slice_robustness"],
    },
    5: {
        "claim": "Alpha confidence ranks after-cost opportunities and is calibrated enough for downstream thresholds.",
        "target_definition": "After-cost alpha/confidence label by horizon.",
        "required_metrics": ["auroc", "pr_auc", "brier_score", "ece", "decile_return", "feature_importance"],
    },
    6: {
        "claim": "Dynamic risk policy improves risk-adjusted exposure without expanding tail loss.",
        "target_definition": "Risk posture conditioned on alpha, target state, and event context.",
        "required_metrics": ["risk_adjusted_return", "max_drawdown", "tail_loss", "policy_stability", "cost_sensitivity"],
    },
    7: {
        "claim": "Position projection predicts exposure path well enough to constrain actions.",
        "target_definition": "Projected exposure path and position behavior.",
        "required_metrics": ["exposure_path_error", "overshoot_rate", "churn_rate", "path_slice_robustness"],
    },
    8: {
        "claim": "Underlying action thesis improves utility after costs and risk controls.",
        "target_definition": "Direct underlying action class and plan utility.",
        "required_metrics": ["action_confusion", "action_utility", "false_action_rate", "missed_opportunity_rate", "slice_robustness"],
    },
    9: {
        "claim": "Option expression improves or safely abstains relative to direct underlying thesis.",
        "target_definition": "Option expression fit, liquidity, IV, and no-option fallback.",
        "required_metrics": ["expression_fit", "liquidity_failure_rate", "iv_sensitivity", "no_option_fallback_quality"],
    },
    10: {
        "claim": "Post-replay event governor attributes residual failures and missed opportunities correctly.",
        "target_definition": "Residual event-risk attribution after replay.",
        "required_metrics": ["failure_attribution_precision", "missed_event_rate", "false_block_rate", "event_regime_stability"],
    },
}

METRIC_FAMILY_DESCRIPTIONS = {
    "representation_context": "State/context coverage, stability, separability, and baseline improvement.",
    "calibrated_prediction": "Binary probabilistic prediction metrics with valid point-in-time labels.",
    "ranking_alpha": "Rank, spread, and score-bucket calibration for alpha/return ordering.",
    "policy_utility": "Risk-policy and allocation utility under realistic constraints.",
    "path_projection": "Projected path accuracy for exposure, risk, and state trajectories.",
    "action_plan": "Action thesis, entry/target/stop, regret, and abstention quality.",
    "option_expression": "Option contract/expression fit, feasibility, and payoff quality.",
    "event_attribution": "Event-risk recall, attribution, intervention, and opportunity-cost quality.",
    "integrity": "Point-in-time, leakage, lineage, and feasibility guardrails.",
    "group_contribution": "Ablation/counterfactual contribution tests owned by the model group.",
}


def _metric_test(metric_id: str, label: str, family: str, role: str, eligibility: str, note: str) -> dict[str, str]:
    return {
        "metric_id": metric_id,
        "label": label,
        "metric_family": family,
        "role": role,
        "eligibility": eligibility,
        "note": note,
        "status": "insufficient_evidence" if role != "avoid" else "not_applicable",
    }


LAYER_METRIC_TESTS = {
    1: [
        _metric_test("regime_state_coverage", "Regime coverage", "representation_context", "primary", "Requires point-in-time market-state rows by date/session.", "Measures whether the context surface covers the fold without unexplained gaps."),
        _metric_test("regime_transition_stability", "Transition stability", "representation_context", "primary", "Requires ordered regime-state outputs.", "Penalizes unstable state flips near fold boundaries."),
        _metric_test("market_context_baseline_lift", "Baseline lift", "representation_context", "primary", "Requires broad-market labels or proxies.", "Compares state output against naive market buckets."),
        _metric_test("macro_revision_leakage", "Macro/revision leakage", "integrity", "guardrail", "Requires source release clocks and revision timestamps.", "Blocks use of revised or future macro values."),
        _metric_test("trade_pnl_as_regime_score", "Direct trade PnL", "group_contribution", "avoid", "Only allowed as model-group context.", "A broad context layer does not own final trade outcomes."),
    ],
    2: [
        _metric_test("sector_relative_explanatory_power", "Sector-relative explanatory power", "representation_context", "primary", "Requires PIT sector/proxy rows and ETF/peer outcomes.", "Measures sector context beyond Layer 1."),
        _metric_test("proxy_mapping_accuracy", "Proxy mapping accuracy", "representation_context", "primary", "Requires timestamped sector/proxy mapping evidence.", "Checks ETF/industry proxy relevance and stability."),
        _metric_test("sector_residual_reduction", "Residual reduction vs L1", "group_contribution", "primary", "Requires counterfactual residual study with Layer 1 held fixed.", "Measures marginal context value over market regime."),
        _metric_test("sector_map_survivorship", "Sector map survivorship", "integrity", "guardrail", "Requires point-in-time membership/proxy evidence.", "Blocks future sector membership leakage."),
        _metric_test("target_trade_outcome_as_sector_score", "Target trade outcome", "group_contribution", "avoid", "Only allowed in model-group attribution.", "A sector context layer does not own target action or execution."),
    ],
    3: [
        _metric_test("target_state_completeness", "State completeness", "representation_context", "primary", "Requires target-state vector rows and expected block schema.", "Measures coverage, missingness, and block completeness."),
        _metric_test("baseline_ladder_improvement", "Baseline ladder improvement", "representation_context", "primary", "Requires target-state labels and baseline ladder definitions.", "Compares representation against naive/current-state baselines."),
        _metric_test("state_quantile_separation", "Future-outcome quantile separation", "representation_context", "primary", "Requires future labels kept outside inference features.", "Checks whether state buckets separate future outcomes."),
        _metric_test("target_identity_leakage", "Target identity leakage", "integrity", "guardrail", "Requires anonymous target candidate and split evidence.", "Blocks company identity leakage into fitting vectors."),
        _metric_test("single_auroc_for_state_vector", "Single state-vector AUROC", "calibrated_prediction", "avoid", "Only allowed for an explicit binary probability head.", "A representation is not one binary classifier."),
    ],
    4: [
        _metric_test("event_failure_precision_recall", "Event failure precision/recall", "event_attribution", "primary", "Requires known-event failure labels with PIT visibility.", "Measures event-family failure detection quality."),
        _metric_test("event_failure_auroc_pr_auc", "Failure AUROC / PR-AUC", "calibrated_prediction", "primary", "Requires explicit binary probabilistic failure label.", "Valid only for probability of known event failure."),
        _metric_test("lead_time_usefulness", "Lead-time usefulness", "event_attribution", "primary", "Requires event visibility time and decision time.", "Measures whether risk arrived early enough."),
        _metric_test("post_event_article_leakage", "Post-event article leakage", "integrity", "guardrail", "Requires article/source timestamps.", "Blocks later coverage in pre-alpha risk."),
        _metric_test("post_replay_residual_as_pre_alpha_input", "Post-replay residual attribution", "event_attribution", "avoid", "Owned by Layer 10, not Layer 4.", "Residual attribution must not leak into pre-alpha risk."),
    ],
    5: [
        _metric_test("rank_ic_by_horizon", "Rank IC by horizon", "ranking_alpha", "primary", "Requires after-cost future return labels by horizon.", "Measures alpha-confidence ordering quality."),
        _metric_test("decile_spread_after_cost", "After-cost decile spread", "ranking_alpha", "primary", "Requires score buckets and cost-adjusted outcomes.", "Checks whether higher scores realize better outcomes."),
        _metric_test("expected_realized_calibration", "Expected vs realized calibration", "ranking_alpha", "primary", "Requires score buckets and realized after-cost return.", "Measures score magnitude calibration."),
        _metric_test("positive_alpha_auroc_brier_ece", "Positive alpha AUROC / Brier / ECE", "calibrated_prediction", "primary", "Requires explicit probability of positive after-cost return.", "Valid only for a probabilistic binary alpha head."),
        _metric_test("purged_embargoed_cv", "Purged / embargoed CV", "integrity", "guardrail", "Requires overlapping horizon metadata.", "Prevents horizon overlap and future label bleed."),
        _metric_test("uncosted_win_rate", "Uncosted win rate", "ranking_alpha", "avoid", "Must be cost/slippage adjusted.", "Raw win rate overstates alpha quality."),
    ],
    6: [
        _metric_test("risk_budget_utility", "Risk budget utility", "policy_utility", "primary", "Requires intended risk budget and realized risk evidence.", "Measures risk-adjusted exposure value."),
        _metric_test("volatility_target_error", "Volatility targeting error", "policy_utility", "primary", "Requires ex-ante target risk and realized volatility.", "Checks realized risk versus intended risk."),
        _metric_test("tail_loss_reduction", "Tail-loss reduction", "policy_utility", "primary", "Requires counterfactual baseline policy.", "Measures drawdown/tail containment value."),
        _metric_test("hard_limit_compliance", "Hard-limit compliance", "integrity", "guardrail", "Requires timestamped account-independent limits.", "Blocks budget or exposure violations."),
        _metric_test("auroc_as_risk_policy_primary", "AUROC primary score", "calibrated_prediction", "avoid", "Only allowed for an explicit binary risk-event probability.", "Risk policy is a utility/constraint layer."),
    ],
    7: [
        _metric_test("exposure_path_error", "Exposure path error", "path_projection", "primary", "Requires projected and realized exposure paths.", "Measures delta/notional/gross/net projection accuracy."),
        _metric_test("holding_period_accuracy", "Holding-period accuracy", "path_projection", "primary", "Requires planned and realized holding path labels.", "Checks duration and turnover fit."),
        _metric_test("risk_trajectory_calibration", "Risk trajectory calibration", "path_projection", "primary", "Requires projected and realized risk trajectory.", "Measures path risk calibration."),
        _metric_test("position_state_timestamp_audit", "Position timestamp audit", "integrity", "guardrail", "Requires point-in-time position state evidence.", "Blocks future fills/account state in projection."),
        _metric_test("final_pnl_as_projection_metric", "Final PnL", "group_contribution", "avoid", "Only allowed as group contribution context.", "Projection does not own action execution."),
    ],
    8: [
        _metric_test("target_before_stop_rate", "Target-before-stop rate", "action_plan", "primary", "Requires realistic path labels after planned entry.", "Measures price-path quality of the action thesis."),
        _metric_test("realized_action_utility", "Realized action utility", "policy_utility", "primary", "Requires cost/slippage-adjusted action outcomes.", "Measures realized utility by action bucket."),
        _metric_test("regret_vs_feasible_baseline", "Regret vs feasible baseline", "action_plan", "primary", "Requires feasible baseline action set.", "Compares selected action to available alternatives."),
        _metric_test("abstention_quality", "Abstention quality", "action_plan", "primary", "Requires no-trade opportunity-cost and avoided-loss labels.", "Measures missed good trades and avoided bad trades."),
        _metric_test("intrabar_path_leakage", "Intrabar path leakage", "integrity", "guardrail", "Requires bar/path timing rules.", "Blocks impossible target/stop ordering assumptions."),
        _metric_test("uncosted_action_win_rate", "Uncosted action win rate", "action_plan", "avoid", "Must include costs/slippage and feasibility.", "Raw win rate can reward bad risk/reward."),
    ],
    9: [
        _metric_test("contract_selection_quality", "Contract selection quality", "option_expression", "primary", "Requires PIT option candidates and selected contract outcome labels.", "Measures selected contract quality versus feasible candidates."),
        _metric_test("option_profit_auroc_pr_auc", "Option profit AUROC / PR-AUC", "calibrated_prediction", "primary", "Requires explicit binary probability of profitable option outcome.", "Valid only for a binary option label."),
        _metric_test("premium_efficiency", "Premium efficiency", "option_expression", "primary", "Requires premium, payoff, and spread-adjusted return labels.", "Measures payoff per premium/spread risk."),
        _metric_test("greeks_iv_liquidity_fit", "Greeks / IV / liquidity fit", "option_expression", "primary", "Requires PIT chain Greeks, IV/skew/term, NBBO, OI/volume.", "Checks expression feasibility and thesis alignment."),
        _metric_test("option_chain_timestamp_purity", "Option chain timestamp purity", "integrity", "guardrail", "Requires chain snapshot clocks and contract availability.", "Blocks expired/survivorship or future chain leakage."),
        _metric_test("underlying_only_pnl_as_option_score", "Underlying-only PnL", "option_expression", "avoid", "Only valid as comparison context.", "Option layer must be judged on option outcomes and feasibility."),
    ],
    10: [
        _metric_test("residual_event_attribution_accuracy", "Residual event attribution accuracy", "event_attribution", "primary", "Requires post-replay event-failure attribution labels.", "Measures attribution to the right event family."),
        _metric_test("intervention_precision_recall", "Intervention precision/recall", "event_attribution", "primary", "Requires reviewed intervention/failure labels.", "Measures false block and false allow quality."),
        _metric_test("avoided_loss_opportunity_cost", "Avoided loss / opportunity cost", "policy_utility", "primary", "Requires counterfactual and opportunity-cost accounting.", "Balances avoided losses against missed winners."),
        _metric_test("severity_calibration", "Severity calibration", "event_attribution", "primary", "Requires severity labels or reviewed ordinal outcomes.", "Checks warning severity versus realized residual risk."),
        _metric_test("post_replay_to_inference_leakage", "Post-replay leakage", "integrity", "guardrail", "Requires explicit inference-time route separation.", "Blocks replay-only evidence from live inference."),
        _metric_test("causal_avoided_loss_claim", "Causal avoided-loss claim", "event_attribution", "avoid", "Requires counterfactual evidence before causality.", "Avoided loss is not causal proof by default."),
    ],
}

MODEL_GROUP_SUPPLEMENTAL_TESTS = [
    _metric_test("layer_ablation", "Layer ablation", "group_contribution", "primary", "Requires replay with one layer removed/frozen.", "Measures end-to-end layer impact without relabeling group PnL as layer-local."),
    _metric_test("layer_replacement_baseline", "Layer replacement baseline", "group_contribution", "primary", "Requires null, heuristic, or previous-version substitute.", "Compares each layer against a controlled baseline."),
    _metric_test("sequential_contribution", "Sequential contribution", "group_contribution", "primary", "Requires L1->L10 incremental replay.", "Measures marginal contribution as layers are added."),
    _metric_test("cross_layer_consistency", "Cross-layer consistency", "group_contribution", "guardrail", "Requires full decision audit trail.", "Detects contradictory layer states."),
    _metric_test("interaction_stress", "Interaction stress", "group_contribution", "guardrail", "Requires earnings/Fed/halt/volatility-shock windows.", "Tests stack behavior in known difficult regimes."),
]


def _read_latest(storage_root: Path, contract_type: str) -> dict[str, Any] | None:
    path = storage_root / "06_dashboard_cache" / "read_models" / contract_type / "latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _chart(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    chart = payload.get("chart_payload") if isinstance(payload, Mapping) else None
    return chart if isinstance(chart, dict) else {}


def _tasks(historical: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    task_timeline = _chart(historical).get("task_timeline")
    return [dict(task) for task in task_timeline] if isinstance(task_timeline, list) else []


def _task_row_key(task: Mapping[str, Any]) -> str:
    return str(task.get("task_uid") or f"{task.get('month') or 'unknown'}:{task.get('task_id') or 'unknown'}")


def _layer_tasks(tasks: list[dict[str, Any]], layer: int) -> list[dict[str, Any]]:
    if layer == 10:
        return [task for task in tasks if task.get("task_id") == "model_group.model_10_event_risk_governor" or task.get("layer") == 10]
    return [task for task in tasks if task.get("layer") == layer]


def _task_status(task: Mapping[str, Any]) -> str:
    return str(task.get("status") or task.get("task_state") or "unknown")


def _layer_status(layer_tasks: list[dict[str, Any]]) -> str:
    if not layer_tasks:
        return "not_started"
    statuses = {_task_status(task).lower() for task in layer_tasks}
    states = {str(task.get("task_state") or "").lower() for task in layer_tasks}
    if "failed" in statuses or "failed" in states:
        return "failed"
    if {"running", "ready"} & statuses or "current" in states:
        return "running"
    if all(
        _task_status(task).lower() in {"succeeded", "not_applicable"}
        or str(task.get("task_state") or "").lower() in {"completed", "skipped"}
        for task in layer_tasks
    ):
        return "completed"
    if "blocked" in statuses or "future" in states:
        return "blocked"
    return "in_progress"


def _latest_update(layer_tasks: list[dict[str, Any]]) -> str | None:
    timestamps = [
        str(value)
        for task in layer_tasks
        for value in (
            task.get("status_updated_at_utc"),
            task.get("updated_at_utc"),
            task.get("ended_at_utc"),
            task.get("started_at_utc"),
            task.get("created_at_utc"),
        )
        if value
    ]
    return max(timestamps) if timestamps else None


def _task_detail(task: Mapping[str, Any]) -> Mapping[str, Any]:
    detail = task.get("detail")
    return detail if isinstance(detail, Mapping) else {}


def _task_blockers(layer_tasks: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for task in layer_tasks:
        detail = _task_detail(task)
        raw = detail.get("blockers")
        if isinstance(raw, list):
            blockers.extend(str(item) for item in raw if item)
        elif task.get("blocker_count"):
            blockers.append(f"{task.get('task_id') or 'task'} reported {task.get('blocker_count')} blockers")
    return sorted(set(blockers))


def _receipt_refs(task: Mapping[str, Any]) -> list[str]:
    detail = _task_detail(task)
    refs = detail.get("receipt_refs")
    return [str(ref) for ref in refs] if isinstance(refs, list) else []


def _has_model_output_receipt(task: Mapping[str, Any]) -> bool:
    model_output_markers = (
        "__model_generation__",
        "__model_training__",
        "/model_generation/",
        "/model_training/",
        "model_generation",
        "model_training",
    )
    return any(any(marker in ref for marker in model_output_markers) for ref in _receipt_refs(task))


def _has_completed_model_output(task: Mapping[str, Any]) -> bool:
    status = _task_status(task).lower()
    state = str(task.get("task_state") or "").lower()
    progress = _task_detail(task).get("progress")
    progress_status = str(progress.get("status") or "").lower() if isinstance(progress, Mapping) else ""
    is_complete = status == "succeeded" or state == "completed" or progress_status == "complete"
    return is_complete and _has_model_output_receipt(task)


def _version_for_layer(layer: int, model_id: str, layer_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    model_tasks = [task for task in layer_tasks if str(task.get("stage_type") or "") in {"model_generation", "model_task"} or "model" in str(task.get("task_id") or "")]
    materialized_tasks = [task for task in model_tasks if _has_completed_model_output(task)]
    if not materialized_tasks:
        return None
    latest = max(materialized_tasks, key=lambda task: str(task.get("status_updated_at_utc") or task.get("updated_at_utc") or task.get("created_at_utc") or ""))
    receipts = _receipt_refs(latest)
    month = str(latest.get("month") or "unknown_period")
    status = _task_status(latest)
    return {
        "version_id": f"{month}:{model_id}",
        "model_id": model_id,
        "layer": layer,
        "run_id": _task_row_key(latest),
        "artifact_ref": receipts[-1] if receipts else None,
        "role": "candidate",
        "lifecycle_status": status,
        "evaluation_status": None,
        "promotion_status": None,
        "updated_at_utc": latest.get("status_updated_at_utc") or latest.get("updated_at_utc"),
        "summary": f"{latest.get('task_label') or model_id} is {status}.",
    }


def _normalize_model_ref(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("model_ref", "version_id", "model_version", "run_id", "artifact_ref", "id", "path", "ref"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
    return ""


def _active_ref(runtime: Mapping[str, Any] | None) -> str | None:
    pointer = _chart(runtime).get("active_model_pointer")
    if not isinstance(pointer, Mapping):
        return None
    return _normalize_model_ref(pointer.get("selected_active_model_ref")) or _normalize_model_ref(pointer.get("new_active_config_ref")) or None


def _ref_matches_layer(ref: str | None, layer: int, model_id: str) -> bool:
    if not ref:
        return False
    normalized = ref.lower()
    return model_id in normalized or f"layer_{layer:02d}" in normalized or f"model_{layer:02d}" in normalized


def _global_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    matches = [task for task in tasks if task.get("task_id") == task_id]
    if not matches:
        return None
    return max(matches, key=lambda task: str(task.get("status_updated_at_utc") or task.get("updated_at_utc") or task.get("created_at_utc") or ""))


def _task_summary(task: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not task:
        return None
    return {
        "status": _task_status(task),
        "summary": str(task.get("reason") or task.get("task_label") or "Task evidence is present."),
        "updated_at_utc": task.get("status_updated_at_utc") or task.get("updated_at_utc"),
    }


def _freshness(payloads: list[Mapping[str, Any] | None]) -> dict[str, Any]:
    generated_values = [str(payload.get("generated_at_utc")) for payload in payloads if isinstance(payload, Mapping) and payload.get("generated_at_utc")]
    return {
        "class": "derived_model_lifecycle_summary",
        "status": "fresh" if generated_values else "no_source_summary",
        "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS,
    }


def _source_refs(historical: Mapping[str, Any] | None, runtime: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return [
        {"contract_type": HISTORICAL_TASK_PROGRESS_CONTRACT, "included": bool(historical)},
        {"contract_type": EXECUTION_RUNTIME_STATUS_CONTRACT, "included": bool(runtime)},
    ]


def _exclusion_issue_refs(exclusions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not exclusions:
        return []
    counts: dict[str, int] = {}
    for exclusion in exclusions:
        for reason_code in exclusion.get("reason_codes") or []:
            key = str(reason_code)
            counts[key] = counts.get(key, 0) + 1
    return [
        {
            "issue_id": "model_group_promotion_evidence_excluded",
            "severity": "medium",
            "summary": f"{len(exclusions)} model-group promotion artifacts were excluded from dashboard analysis because they are not valid scoped promotion evidence.",
            "reason_counts": counts,
        }
    ]


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _layer_evaluation_artifact_path(storage_root: Path, model_id: str) -> Path:
    return storage_root / LAYER_EVALUATION_ARTIFACT_DIR / model_id / "layer_evaluation_summary_latest.json"


def _legacy_layer_evaluation_source(storage_root: Path, model_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    model_root = storage_root / LAYER_EVALUATION_ARTIFACT_DIR / model_id
    candidates = sorted(model_root.glob("evaluation_summary_*.json"))
    dated_candidates = [path for path in candidates if re.match(r"evaluation_summary_\d{4}-\d{2}\.json$", path.name)]
    search_order = list(reversed(dated_candidates or candidates))
    for path in search_order:
        payload = _load_json_object(path)
        if payload is not None:
            return path, payload
    return None, None


def _metric_summary_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    metrics = payload.get("metric_value_summary")
    if isinstance(metrics, Mapping):
        return [
            {
                "metric_id": str(metric_id),
                "value": value,
                "source": "metric_value_summary",
                "status": "published" if value is not None else "not_published",
            }
            for metric_id, value in sorted(metrics.items())
        ]
    tables = payload.get("tables")
    metric_rows = tables.get("model_promotion_metric") if isinstance(tables, Mapping) else None
    if isinstance(metric_rows, list):
        rows = []
        for row in metric_rows:
            if not isinstance(row, Mapping):
                continue
            metric_name = row.get("metric_name")
            if not metric_name:
                continue
            rows.append(
                {
                    "metric_id": str(metric_name),
                    "value": row.get("metric_value"),
                    "source": "tables.model_promotion_metric",
                    "status": "published" if row.get("metric_value") is not None else "not_published",
                    "detail": row.get("metric_payload_json") if isinstance(row.get("metric_payload_json"), Mapping) else None,
                }
            )
        return rows
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        rows = []
        for metric_id in ("model_row_count", "outcome_row_count", "label_row_count", "label_join_coverage_rate"):
            value = summary.get(metric_id)
            if isinstance(value, (int, float)):
                rows.append(
                    {
                        "metric_id": metric_id,
                        "value": value,
                        "source": "summary",
                        "status": "published",
                    }
                )
        leakage_check = summary.get("leakage_check_passed")
        if isinstance(leakage_check, bool):
            rows.append(
                {
                    "metric_id": "leakage_check_passed",
                    "value": 1.0 if leakage_check else 0.0,
                    "source": "summary",
                    "status": "published",
                    "detail": {"raw_value": leakage_check},
                }
            )
        return rows
    return []


def _parameter_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    threshold_payload = payload.get("acceptance_thresholds")
    if isinstance(threshold_payload, Mapping):
        for key, value in sorted(threshold_payload.items()):
            parameters.append(
                {
                    "parameter_id": str(key),
                    "label": str(key),
                    "value": value,
                    "status": "published",
                    "source": "acceptance_thresholds",
                    "role": "evaluation_acceptance_threshold",
                }
            )
    return parameters


def _coefficient_value(item: Mapping[str, Any]) -> Any:
    for key in ("coefficient", "weight", "value", "importance", "gain", "contribution", "score"):
        if key in item:
            return item.get(key)
    return None


def _coefficient_items_from_value(value: Any, *, source: str, role: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, coefficient in sorted(value.items()):
            rows.append(
                {
                    "coefficient_id": str(key),
                    "label": str(key),
                    "value": coefficient,
                    "status": "published",
                    "source": source,
                    "role": role,
                }
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, Mapping):
                label = item.get("label") or item.get("feature") or item.get("factor") or item.get("parameter_id") or item.get("name")
                rows.append(
                    {
                        "coefficient_id": str(item.get("coefficient_id") or label or f"{role}_{index + 1}"),
                        "label": str(label or f"{role}_{index + 1}"),
                        "value": _coefficient_value(item),
                        "status": str(item.get("status") or "published"),
                        "source": source,
                        "role": str(item.get("role") or role),
                        "detail": {k: v for k, v in item.items() if k not in {"coefficient_id", "label", "feature", "factor", "parameter_id", "name", "value", "coefficient", "weight", "importance", "gain", "contribution", "score", "status", "role"}},
                    }
                )
            else:
                rows.append(
                    {
                        "coefficient_id": f"{role}_{index + 1}",
                        "label": f"{role}_{index + 1}",
                        "value": item,
                        "status": "published",
                        "source": source,
                        "role": role,
                    }
                )
    return rows


def _runtime_coefficient_items_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in RUNTIME_COEFFICIENT_PAYLOAD_KEYS:
        rows.extend(_coefficient_items_from_value(payload.get(key), source=key, role=key))
    for container_name in ("summary", "metrics", "model_artifact", "explainability", "diagnostics"):
        container = payload.get(container_name)
        if not isinstance(container, Mapping):
            continue
        for key in RUNTIME_COEFFICIENT_PAYLOAD_KEYS:
            rows.extend(_coefficient_items_from_value(container.get(key), source=f"{container_name}.{key}", role=key))
    return rows


def _parse_lightgbm_feature_importances(booster_model: str, *, source: str, horizon: str, limit: int = 12) -> list[dict[str, Any]]:
    feature_importances: list[tuple[str, float]] = []
    in_section = False
    for line in booster_model.splitlines():
        stripped = line.strip()
        if stripped == "feature_importances:":
            in_section = True
            continue
        if in_section and not stripped:
            break
        if not in_section or "=" not in stripped:
            continue
        feature, raw_value = stripped.split("=", 1)
        try:
            value = float(raw_value)
        except ValueError:
            continue
        feature_importances.append((feature, value))
    feature_importances.sort(key=lambda item: item[1], reverse=True)
    return [
        {
            "coefficient_id": f"{horizon}:{feature}",
            "label": feature,
            "value": value,
            "status": "published",
            "source": source,
            "role": "runtime_feature_importance",
            "detail": {"horizon": horizon, "rank": index + 1},
        }
        for index, (feature, value) in enumerate(feature_importances[:limit])
    ]


def _runtime_coefficient_items_from_model_artifacts(model_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not model_dir.exists():
        return rows
    for path in sorted(model_dir.glob("*.json")):
        if path.name.startswith(("evaluation_summary", "layer_evaluation_summary")):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        rows.extend(_runtime_coefficient_items_from_payload(payload))
        artifacts_by_horizon = payload.get("artifacts_by_horizon")
        if isinstance(artifacts_by_horizon, Mapping):
            for horizon, artifact in sorted(artifacts_by_horizon.items()):
                booster_model = artifact.get("booster_model") if isinstance(artifact, Mapping) else None
                if isinstance(booster_model, str):
                    rows.extend(
                        _parse_lightgbm_feature_importances(
                            booster_model,
                            source=str(path),
                            horizon=str(horizon),
                        )
                    )
    return rows


def _runtime_coefficient_items(payload: Mapping[str, Any], *, model_dir: Path) -> list[dict[str, Any]]:
    rows = _runtime_coefficient_items_from_payload(payload)
    rows.extend(_runtime_coefficient_items_from_model_artifacts(model_dir))
    return rows


def _population_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    tables = payload.get("tables")
    if isinstance(tables, Mapping):
        row_counts: dict[str, Any] = {}
        for key, value in tables.items():
            if isinstance(value, (int, float)):
                row_counts[str(key)] = value
            elif isinstance(value, list):
                row_counts[str(key)] = len(value)
        if row_counts:
            return {"status": "published", "row_counts": row_counts}
    database_summary = payload.get("database_summary_evaluation")
    row_counts = database_summary.get("row_counts") if isinstance(database_summary, Mapping) else None
    if isinstance(row_counts, Mapping):
        return {"status": "published", "row_counts": dict(row_counts)}
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        row_counts = {}
        for source_key, row_key in (
            ("model_row_count", "model_rows"),
            ("outcome_row_count", "outcome_rows"),
            ("label_row_count", "label_rows"),
        ):
            value = summary.get(source_key)
            if isinstance(value, (int, float)):
                row_counts[row_key] = value
        labels = payload.get("labels")
        if isinstance(labels, list):
            row_counts.setdefault("labels", len(labels))
        if row_counts:
            return {"status": "published", "row_counts": row_counts}
    return {"status": "not_published", "row_counts": {}}


def _artifact_status_from_legacy(payload: Mapping[str, Any] | None) -> tuple[str, str]:
    if payload is None:
        return "insufficient_evidence", "No source evaluation summary has been published for this layer."
    failed = payload.get("failed_thresholds")
    if isinstance(failed, Mapping) and failed:
        return "failed_validity", f"{len(failed)} acceptance thresholds failed."
    run_status = str(payload.get("run_status") or payload.get("request_status") or "").lower()
    if run_status in {"completed", "evaluated", "passed"}:
        return "evaluated", "Layer evaluation summary was normalized from a legacy evaluation artifact."
    database_summary = payload.get("database_summary_evaluation")
    if isinstance(database_summary, Mapping) and str(database_summary.get("status") or "").startswith("completed"):
        return "evaluated_summary_mode", "Layer evaluation summary was normalized from a summary-mode database evaluation artifact."
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        model_rows = summary.get("model_row_count")
        label_rows = summary.get("label_row_count")
        if isinstance(model_rows, (int, float)) and model_rows > 0 and isinstance(label_rows, (int, float)) and label_rows > 0:
            return "evaluated_local_deferred", "Layer local evaluation summary was normalized from model rows and labels; production validity remains deferred."
    return "insufficient_evidence", "Source evaluation summary exists but does not publish a completed evaluation status."


def _legacy_fold_id(path: Path | None, version: Mapping[str, Any] | None) -> str | None:
    version_id = str((version or {}).get("version_id") or "")
    if version_id:
        return version_id.split(":", 1)[0]
    if path is None:
        return None
    match = re.search(r"evaluation_summary_(?P<month>\d{4}-\d{2})\.json$", path.name)
    return f"fold_{match.group('month')}" if match else None


def _source_ref(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _layer_evaluation_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "storage://trading-storage/03_model_artifacts/schemas/layer_evaluation_summary.schema.json",
        "title": LAYER_EVALUATION_SUMMARY_CONTRACT,
        "type": "object",
        "required": [
            "contract_type",
            "schema_version",
            "generated_at_utc",
            "source_system",
            "layer",
            "layer_id",
            "model_id",
            "evaluation_status",
            "validity_status",
            "evaluation_population",
            "metric_values",
            "parameter_values",
            "runtime_coefficients",
            "source_artifact_refs",
            "schema_ref",
        ],
        "additionalProperties": True,
        "properties": {
            "contract_type": {"const": LAYER_EVALUATION_SUMMARY_CONTRACT},
            "schema_version": {"type": "integer", "minimum": 1},
            "generated_at_utc": {"type": "string", "format": "date-time"},
            "source_system": {"type": "string", "minLength": 1},
            "layer": {"type": "integer", "minimum": 1, "maximum": 10},
            "layer_id": {"type": "string", "minLength": 1},
            "model_id": {"type": "string", "minLength": 1},
            "evaluation_status": {"type": "string", "minLength": 1},
            "validity_status": {"type": "string", "minLength": 1},
            "evaluation_population": {"type": "object"},
            "metric_values": {"type": "array"},
            "parameter_values": {"type": "array"},
            "runtime_coefficients": {"type": "array"},
            "source_artifact_refs": {"type": "array"},
            "schema_ref": {"type": "string", "minLength": 1},
        },
    }


def _build_layer_evaluation_artifact(
    *,
    storage_root: Path,
    layer: int,
    model_id: str,
    name: str,
    version: Mapping[str, Any] | None,
    generated_at_utc: str,
) -> dict[str, Any]:
    legacy_path, legacy_payload = _legacy_layer_evaluation_source(storage_root, model_id)
    status, reason = _artifact_status_from_legacy(legacy_payload)
    metric_values = _metric_summary_items(legacy_payload or {})
    parameter_values = _parameter_items(legacy_payload or {})
    runtime_coefficients = _runtime_coefficient_items(
        legacy_payload or {},
        model_dir=storage_root / LAYER_EVALUATION_ARTIFACT_DIR / model_id,
    )
    population = _population_summary(legacy_payload or {})
    source_ref = _source_ref(legacy_path)
    return {
        "contract_type": LAYER_EVALUATION_SUMMARY_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "layer": layer,
        "layer_id": f"layer_{layer:02d}",
        "model_id": model_id,
        "name": name,
        "version_id": (version or {}).get("version_id"),
        "fold_id": _legacy_fold_id(legacy_path, version),
        "evaluation_status": status,
        "validity_status": status if status in {"evaluated", "failed_validity"} else "insufficient_evidence",
        "validity_reason": reason,
        "evaluation_population": population,
        "metric_values": metric_values,
        "parameter_values": parameter_values,
        "runtime_coefficients": runtime_coefficients,
        "source_artifact_refs": [source_ref] if source_ref else [],
        "missing_evidence": [] if legacy_payload is not None else ["source_evaluation_summary"],
        "schema_ref": LAYER_EVALUATION_SUMMARY_SCHEMA_REF,
    }


def materialize_layer_evaluation_summary_artifacts(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    generated_at_utc: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize per-layer evaluation artifacts under storage/03_model_artifacts."""

    generated_at_utc = generated_at_utc or now_utc()
    storage_root = Path(storage_root)
    layer_payload = build_model_layer_readiness_summary(storage_root=storage_root, generated_at_utc=generated_at_utc)
    lifecycle_by_layer = {
        int(layer["layer"]): layer
        for layer in _chart(layer_payload).get("layers", [])
        if isinstance(layer, Mapping) and isinstance(layer.get("layer"), int)
    }
    schema_path = storage_root / "03_model_artifacts" / "schemas" / "layer_evaluation_summary.schema.json"
    _write_atomic_json(schema_path, _layer_evaluation_schema())
    artifacts = []
    for layer, model_id, name in MODEL_LAYERS:
        lifecycle = lifecycle_by_layer.get(layer, {})
        versions = lifecycle.get("versions") if isinstance(lifecycle.get("versions"), list) else []
        version = versions[0] if versions and isinstance(versions[0], Mapping) else None
        artifact = _build_layer_evaluation_artifact(
            storage_root=storage_root,
            layer=layer,
            model_id=model_id,
            name=name,
            version=version,
            generated_at_utc=generated_at_utc,
        )
        _write_atomic_json(_layer_evaluation_artifact_path(storage_root, model_id), artifact)
        artifacts.append(artifact)
    return artifacts


def _load_layer_evaluation_artifacts(storage_root: Path) -> dict[int, dict[str, Any]]:
    artifacts: dict[int, dict[str, Any]] = {}
    for layer, model_id, _name in MODEL_LAYERS:
        artifact = _load_json_object(_layer_evaluation_artifact_path(storage_root, model_id))
        if artifact and artifact.get("contract_type") == LAYER_EVALUATION_SUMMARY_CONTRACT:
            artifacts[layer] = artifact
    return artifacts


def _artifact_metric_lookup(metric_values: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    lookup: dict[str, Mapping[str, Any]] = {}
    for item in metric_values:
        metric_id = str(item.get("metric_id") or "")
        if metric_id:
            lookup[metric_id] = item
    return lookup


def _mean_metric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Mapping):
        mean = value.get("mean")
        if isinstance(mean, (int, float)):
            return float(mean)
        metric_value = value.get("value")
        if isinstance(metric_value, (int, float)):
            return float(metric_value)
    return None


def _model_group_version_label(*, fold_id: str, candidate_model_ref: str, target_symbol: str, fallback: str) -> str:
    source = " ".join(item for item in [fold_id, candidate_model_ref, fallback] if item)
    target = target_symbol.strip().upper()
    compact_match = re.search(
        r"(?P<year>20\d{2})[-_ ]?fold[-_ ]?(?P<fold>\d+)",
        source,
        flags=re.IGNORECASE,
    )
    if compact_match:
        label = f"{compact_match.group('year')} fold{int(compact_match.group('fold'))}"
        return f"{target} {label}" if target else f"Unscoped {label}"

    range_match = re.search(
        r"(?P<year>20\d{2})-(?P<start_month>\d{2})_(?P=year)-(?P<end_month>\d{2})",
        source,
    )
    if range_match:
        start_month = int(range_match.group("start_month"))
        fold_number = ((start_month - 1) // 6) + 1
        label = f"{range_match.group('year')} fold{fold_number}"
        return f"{target} {label}" if target else f"Unscoped {label}"

    return fallback


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return {stripped.upper()} if stripped else set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip().upper() for item in value if str(item).strip()}
    return set()


def _model_group_version_scope_mismatch(decision: Mapping[str, Any], settlement: Mapping[str, Any] | None, target_symbol: str) -> str | None:
    replay_ref = str(
        decision.get("replay_validation_ref")
        or decision.get("replay_result_ref")
        or (settlement.get("replay_result_ref") if isinstance(settlement, Mapping) else "")
        or ""
    )
    if not replay_ref:
        return None
    replay_receipt = _load_json_object(Path(replay_ref))
    if replay_receipt is None:
        return None
    candidate_ref = str(replay_receipt.get("candidate_model_ref") or "")
    if "current_deterministic_crypto_policy" in candidate_ref:
        return "replay receipt used deterministic crypto placeholder policy"
    target_refs = _string_set(replay_receipt.get("target_refs") or replay_receipt.get("candidate_target_refs"))
    normalized_target = str(target_symbol or "").strip().upper()
    if normalized_target and target_refs and normalized_target not in target_refs:
        return f"replay receipt targets {', '.join(sorted(target_refs))} do not include model target {normalized_target}"
    return None


def _model_group_version_exclusion_reasons(
    *,
    decision: Mapping[str, Any],
    settlement: Mapping[str, Any] | None,
    target_symbol: str,
    candidate_model_ref: str,
) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    normalized_target = target_symbol.strip().upper()
    if not normalized_target:
        reasons.append({"reason_code": "missing_target_symbol", "reason": "promotion artifact does not declare a target_symbol"})
    candidate_target = _target_symbol_from_candidate_ref(candidate_model_ref)
    if not candidate_target:
        reasons.append({"reason_code": "unscoped_candidate_model_ref", "reason": "candidate_model_ref is fold-scoped instead of target-scoped"})
    elif normalized_target and candidate_target != normalized_target:
        reasons.append(
            {
                "reason_code": "candidate_target_mismatch",
                "reason": f"candidate_model_ref target {candidate_target} does not match artifact target {normalized_target}",
            }
        )
    scope_mismatch = _model_group_version_scope_mismatch(decision, settlement, normalized_target)
    if scope_mismatch:
        reasons.append({"reason_code": "replay_scope_target_mismatch", "reason": scope_mismatch})
    return reasons


def _model_group_promotion_preview_overrides(storage_root: Path) -> list[dict[str, Any]]:
    payload = _load_json_object(storage_root / MODEL_GROUP_PROMOTION_PREVIEW_OVERRIDE_PATH)
    if not payload or str(payload.get("status") or "").lower() not in {"enabled", "active"}:
        return []
    overrides = payload.get("overrides")
    return [dict(item) for item in overrides] if isinstance(overrides, list) else []


def _model_group_promotion_preview_override(
    *,
    storage_root: Path,
    fold_id: str,
    target_symbol: str,
    candidate_model_ref: str,
) -> dict[str, Any] | None:
    normalized_fold = fold_id.strip().lower()
    normalized_target = target_symbol.strip().upper()
    normalized_ref = candidate_model_ref.strip().lower()
    for override in _model_group_promotion_preview_overrides(storage_root):
        override_fold = str(override.get("fold_id") or "").strip().lower()
        override_target = str(override.get("target_symbol") or "").strip().upper()
        override_ref = str(override.get("candidate_model_ref") or "").strip().lower()
        fold_matches = not override_fold or override_fold == normalized_fold
        target_matches = not override_target or override_target == normalized_target
        ref_matches = not override_ref or override_ref == normalized_ref
        if fold_matches and target_matches and ref_matches:
            return override
    return None


def _diagnostic_availability(metrics: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    feature = metrics.get("feature_diagnostics") if isinstance(metrics.get("feature_diagnostics"), Mapping) else {}
    scorecards = metrics.get("scorecards") if isinstance(metrics.get("scorecards"), Mapping) else {}
    slices = scorecards.get("slices") if isinstance(scorecards.get("slices"), Mapping) else {}
    silhouette = feature.get("silhouette") if isinstance(feature.get("silhouette"), Mapping) else {}
    pca = feature.get("pca") if isinstance(feature.get("pca"), Mapping) else {}
    pcoa = feature.get("pcoa") if isinstance(feature.get("pcoa"), Mapping) else {}
    feature_available = bool(pca.get("available") or pcoa.get("available"))
    slice_available = bool(any(isinstance(value, list) and value for value in slices.values()))
    silhouette_available = bool(any(value is not None for value in silhouette.values()))
    return {
        "feature_space": {
            "status": "available" if feature_available else "unavailable",
            "reason_code": "feature_space_published" if feature_available else "missing_feature_space_diagnostics",
        },
        "silhouette": {
            "status": "available" if silhouette_available else "unavailable",
            "reason_code": "silhouette_published" if silhouette_available else "missing_silhouette_diagnostics",
        },
        "slice_distribution": {
            "status": "available" if slice_available else "unavailable",
            "reason_code": "scorecard_slices_published" if slice_available else "missing_slice_scorecards",
        },
    }


def _model_group_promotion_evidence(storage_root: Path, *, active_ref: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    review_root = storage_root / "05_replay_datasets" / "promotion_replay_candidate_policy" / "promotion_review_runs"
    if not review_root.exists():
        return [], []
    rows_by_version_key: dict[str, dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    for decision_path in sorted(review_root.glob("*/promotion_eligibility_decision.json")):
        decision = _load_json_object(decision_path)
        if decision is None:
            continue
        review = _load_json_object(decision_path.parent / "promotion_evaluation_review.json") or {}
        settlement_ref = str(decision.get("settlement_run_ref") or review.get("settlement_run_ref") or "")
        settlement = _load_json_object(Path(settlement_ref)) if settlement_ref else None
        metrics = settlement.get("metrics") if isinstance(settlement, Mapping) and isinstance(settlement.get("metrics"), Mapping) else {}
        decision_status = str(decision.get("decision_status") or "not_reported")
        recommendation = str(decision.get("agent_review_recommendation") or review.get("recommendation") or "")
        candidate_model_ref = str(decision.get("candidate_model_ref") or review.get("candidate_model_ref") or "")
        fold_id = str(decision.get("fold_id") or review.get("fold_id") or "")
        target_symbol = str(
            decision.get("target_symbol")
            or review.get("target_symbol")
            or (settlement.get("target_symbol") if isinstance(settlement, Mapping) else "")
            or _target_symbol_from_candidate_ref(candidate_model_ref)
            or ""
        ).strip().upper()
        exclusion_reasons = _model_group_version_exclusion_reasons(
            decision=decision,
            settlement=settlement,
            target_symbol=target_symbol,
            candidate_model_ref=candidate_model_ref,
        )
        preview_override = _model_group_promotion_preview_override(
            storage_root=storage_root,
            fold_id=fold_id,
            target_symbol=target_symbol,
            candidate_model_ref=candidate_model_ref,
        )
        if exclusion_reasons and not preview_override:
            exclusions.append(
                {
                    "promotion_run_id": decision_path.parent.name,
                    "decision_ref": str(decision_path),
                    "settlement_ref": settlement_ref or None,
                    "fold_id": fold_id or None,
                    "target_symbol": target_symbol or None,
                    "candidate_model_ref": candidate_model_ref or None,
                    "reason_codes": [item["reason_code"] for item in exclusion_reasons],
                    "reasons": exclusion_reasons,
                }
            )
            continue
        if preview_override:
            decision_status = str(preview_override.get("decision_status") or "promoted")
            recommendation = str(preview_override.get("agent_review_recommendation") or recommendation or "preview_override")
            target_symbol = str(preview_override.get("target_symbol") or target_symbol).strip().upper()
            candidate_model_ref = str(preview_override.get("candidate_model_ref") or candidate_model_ref)
        version_key = candidate_model_ref or fold_id or decision_path.parent.name
        version_label = _model_group_version_label(
            fold_id=fold_id,
            candidate_model_ref=candidate_model_ref,
            target_symbol=target_symbol,
            fallback=decision_path.parent.name,
        )
        if preview_override and preview_override.get("identity"):
            identity = str(preview_override.get("identity"))
        elif active_ref and candidate_model_ref and candidate_model_ref == active_ref:
            identity = "active"
        elif decision_status == "eligible":
            identity = "shadow"
        elif decision_status in {"deferred", "rejected", "revoked", "superseded"}:
            identity = "retired"
        else:
            identity = "candidate"
        row = {
            "version_id": version_key,
            "version_label": version_label,
            "promotion_run_id": decision_path.parent.name,
            "fold_id": fold_id,
            "target_symbol": target_symbol or None,
            "candidate_model_ref": candidate_model_ref,
            "identity": identity,
            "decision_status": decision_status,
            "agent_review_recommendation": recommendation,
            "created_at_utc": decision.get("created_at_utc") or review.get("created_at_utc"),
            "updated_at_utc": decision.get("created_at_utc") or review.get("created_at_utc"),
            "metrics": {
                "auroc": metrics.get("auroc"),
                "decision_row_count": metrics.get("decision_row_count"),
                "excess_return_total": metrics.get("excess_return_total"),
                "max_drawdown": metrics.get("max_drawdown"),
                "hit_rate": metrics.get("hit_rate"),
                "brier_score": metrics.get("brier_score"),
                "pr_auc": metrics.get("pr_auc"),
                "base_rate": metrics.get("base_rate"),
                "ece": metrics.get("ece"),
                "mce": metrics.get("mce"),
                "brier_reliability": metrics.get("brier_reliability"),
                "brier_resolution": metrics.get("brier_resolution"),
                "brier_uncertainty": metrics.get("brier_uncertainty"),
                "profit_factor": metrics.get("profit_factor"),
                "return_per_decision": metrics.get("return_per_decision"),
                "tail_loss_p05": metrics.get("tail_loss_p05"),
                "cost_sensitivity_2x": metrics.get("cost_sensitivity_2x"),
                "worst_month_return": metrics.get("worst_month_return"),
                "month_slice_count": metrics.get("month_slice_count"),
                "data_integrity_status": metrics.get("data_integrity_status"),
                "leakage_check_status": metrics.get("leakage_check_status"),
                "decision_variable_schema_status": metrics.get("decision_variable_schema_status"),
                "decision_intended_side_unknown_count": metrics.get("decision_intended_side_unknown_count"),
                "decision_agency_unknown_count": metrics.get("decision_agency_unknown_count"),
                "feature_column_count": metrics.get("feature_column_count"),
                "feature_row_count": metrics.get("feature_row_count"),
                "feature_sample_count": metrics.get("feature_sample_count"),
                "pca_available": metrics.get("pca_available"),
                "pca_variance_pc1": metrics.get("pca_variance_pc1"),
                "pca_variance_pc2": metrics.get("pca_variance_pc2"),
                "pca_variance_top2": metrics.get("pca_variance_top2"),
                "pcoa_available": metrics.get("pcoa_available"),
                "pcoa_variance_pc1": metrics.get("pcoa_variance_pc1"),
                "pcoa_variance_pc2": metrics.get("pcoa_variance_pc2"),
                "pcoa_variance_top2": metrics.get("pcoa_variance_top2"),
                "silhouette_outcome_label": metrics.get("silhouette_outcome_label"),
                "silhouette_decision_action": metrics.get("silhouette_decision_action"),
                "predictive_diagnostics": metrics.get("predictive_diagnostics"),
                "calibration_diagnostics": metrics.get("calibration_diagnostics"),
                "economic_diagnostics": metrics.get("economic_diagnostics"),
                "data_integrity_diagnostics": metrics.get("data_integrity_diagnostics"),
                "temporal_stability_diagnostics": metrics.get("temporal_stability_diagnostics"),
                "baseline_comparison_diagnostics": metrics.get("baseline_comparison_diagnostics"),
                "uncertainty_diagnostics": metrics.get("uncertainty_diagnostics"),
                "feature_diagnostics": metrics.get("feature_diagnostics"),
                "decision_variable_schema_diagnostics": metrics.get("decision_variable_schema_diagnostics"),
                "scorecards": metrics.get("scorecards"),
                "diagnostic_availability": metrics.get("diagnostic_availability") or _diagnostic_availability(metrics),
                "evaluation_disagreement_report": metrics.get("evaluation_disagreement_report"),
            },
            "blocking_issues": [str(item) for item in review.get("blocking_issues") or [] if item],
            "summary": str(decision.get("decision_reason") or review.get("rationale") or ""),
            "refs": {
                "decision_ref": str(decision_path),
                "review_ref": str(decision_path.parent / "promotion_evaluation_review.json"),
                "settlement_ref": settlement_ref,
            },
        }
        if preview_override:
            row["preview_override"] = True
            row["preview_override_reason"] = str(
                preview_override.get("reason")
                or "Temporary dashboard preview override; this does not represent an accepted promotion decision."
            )
            row["excluded_reason_codes_overridden"] = [item["reason_code"] for item in exclusion_reasons]
        existing = rows_by_version_key.get(version_key)
        row_clock = str(row.get("created_at_utc") or row.get("promotion_run_id") or "")
        existing_clock = str((existing or {}).get("created_at_utc") or (existing or {}).get("promotion_run_id") or "")
        if existing is None or row_clock >= existing_clock:
            rows_by_version_key[version_key] = row
    scoped_folds = {
        str(row.get("fold_id") or "")
        for row in rows_by_version_key.values()
        if row.get("target_symbol") and row.get("fold_id")
    }
    rows = [
        row for row in rows_by_version_key.values()
        if row.get("target_symbol") or str(row.get("fold_id") or "") not in scoped_folds
    ]
    return sorted(
        rows,
        key=lambda row: str(row.get("created_at_utc") or row.get("version_id") or ""),
    ), exclusions


def _model_group_promotion_versions(storage_root: Path, *, active_ref: str | None) -> list[dict[str, Any]]:
    rows, _exclusions = _model_group_promotion_evidence(storage_root, active_ref=active_ref)
    return rows


def _target_symbol_from_candidate_ref(candidate_model_ref: str) -> str | None:
    match = re.search(r"/model_group/(?P<target>[A-Za-z0-9_]+)/20\d{2}-\d{2}_20\d{2}-\d{2}$", candidate_model_ref)
    if not match:
        return None
    raw_target = match.group("target").upper()
    if raw_target == "UNKNOWN_TARGET":
        return None
    return raw_target.replace("_", ".")


def build_model_layer_readiness_summary(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the Models page layer lifecycle summary."""

    generated_at_utc = generated_at_utc or now_utc()
    historical = _read_latest(storage_root, HISTORICAL_TASK_PROGRESS_CONTRACT)
    runtime = _read_latest(storage_root, EXECUTION_RUNTIME_STATUS_CONTRACT)
    tasks = _tasks(historical)
    evaluation_task = _global_task(tasks, "model_group.evaluation")
    promotion_task = _global_task(tasks, "model_group.promotion")
    active_ref = _active_ref(runtime)
    group_versions, excluded_group_versions = _model_group_promotion_evidence(storage_root, active_ref=active_ref)
    latest_group_promotion = group_versions[-1] if group_versions else None
    layers = []
    version_count = 0
    active_count = 0
    for layer, model_id, name in MODEL_LAYERS:
        layer_tasks = _layer_tasks(tasks, layer)
        version = _version_for_layer(layer, model_id, layer_tasks)
        versions = [version] if version else []
        version_count += len(versions)
        is_active = _ref_matches_layer(active_ref, layer, model_id)
        active_count += 1 if is_active else 0
        layers.append(
            {
                "layer": layer,
                "layer_id": f"layer_{layer:02d}",
                "model_id": model_id,
                "name": name,
                "status": _layer_status(layer_tasks),
                "lifecycle_status": "active" if is_active else _layer_status(layer_tasks),
                "latest_version_ref": version["version_id"] if version else None,
                "current_version_ref": version["version_id"] if version else None,
                "active_version_ref": active_ref if is_active else None,
                "shadow_version_refs": [],
                "retiring_version_refs": [],
                "eliminated_version_refs": [],
                "versions": versions,
                "evaluation": _task_summary(evaluation_task),
                "promotion": {
                    "status": latest_group_promotion.get("decision_status") if latest_group_promotion else (_task_status(promotion_task) if promotion_task else "not_reported"),
                    "summary": latest_group_promotion.get("summary") if latest_group_promotion else str((promotion_task or {}).get("reason") or "No group promotion evidence has been published yet."),
                    "updated_at_utc": latest_group_promotion.get("updated_at_utc") if latest_group_promotion else ((promotion_task or {}).get("status_updated_at_utc") or (promotion_task or {}).get("updated_at_utc")),
                },
                "blockers": _task_blockers(layer_tasks),
                "latest_updated_at_utc": _latest_update(layer_tasks),
                "summary": f"{name} lifecycle posture derived from dashboard evidence.",
            }
        )
    status = "ready" if layers else "not_started"
    return {
        "contract_type": MODEL_LAYER_READINESS_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": status,
        "severity": "info",
        "summary": f"Models page has {version_count} observed candidate versions and {active_count} active live pointers.",
        "chart_payload": {
            "layers": layers,
            "current_layer": _chart(historical).get("active_task", {}).get("layer") if isinstance(_chart(historical).get("active_task"), Mapping) else None,
            "active_model_ref": active_ref,
            "shadow_model_refs": [],
            "retiring_model_refs": [],
            "eliminated_model_refs": [],
            "group_versions": group_versions,
            "excluded_group_versions": excluded_group_versions,
        },
        "profile_refs": [{"registry_ref": "MODEL_LAYER_READINESS_SUMMARY", "field": "contract_type"}],
        "issue_refs": _exclusion_issue_refs(excluded_group_versions),
        "diagnostic_refs": [],
        "lineage_refs": _source_refs(historical, runtime),
        "freshness": _freshness([historical, runtime]),
        "schema_ref": MODEL_LAYER_READINESS_SCHEMA_REF,
    }


def _layer_evaluation_sections(
    layer: int,
    *,
    version: Mapping[str, Any] | None,
    group_versions: list[dict[str, Any]],
    artifact: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    claim = LAYER_EVALUATION_CLAIMS[layer]
    metric_tests = LAYER_METRIC_TESTS[layer]
    primary_tests = [test["metric_id"] for test in metric_tests if test["role"] == "primary"]
    guardrail_tests = [test["metric_id"] for test in metric_tests if test["role"] == "guardrail"]
    has_version = bool(version)
    has_artifact = bool(artifact)
    artifact_status = str((artifact or {}).get("evaluation_status") or "insufficient_evidence")
    population = artifact.get("evaluation_population") if isinstance(artifact, Mapping) else None
    metric_lookup = _artifact_metric_lookup(
        item for item in (artifact or {}).get("metric_values", []) if isinstance(item, Mapping)
    )
    published_metrics = [metric_id for metric_id, item in metric_lookup.items() if item.get("status") == "published"]
    guardrail_metrics = [metric_id for metric_id in guardrail_tests if metric_id in metric_lookup]
    group_reference_available = bool(group_versions)
    sections = [
        {
            "section_id": "evaluation_population",
            "label": "Evaluation Population",
            "status": "published" if isinstance(population, Mapping) and population.get("status") == "published" else "insufficient_evidence",
            "reason": (
                "Normalized layer_evaluation_summary publishes evaluation population or table-count evidence."
                if isinstance(population, Mapping) and population.get("status") == "published"
                else "Layer task coverage exists, but no layer_evaluation_summary artifact reports holdout rows, exclusions, labels, or split diagnostics."
                if has_version
                else "No completed layer model version is available for evaluation."
            ),
            "required_evidence": ["fold_id", "target_scope", "train_validation_test_rows", "excluded_rows", "label_definition"],
        },
        {
            "section_id": "predictive_evidence",
            "label": "Predictive Evidence",
            "status": "published" if published_metrics else "insufficient_evidence",
            "reason": (
                f"Normalized layer_evaluation_summary publishes {len(published_metrics)} layer metric values."
                if published_metrics
                else "Layer-local metric tests are defined, but no layer-specific holdout metric values are published yet. Group metrics must not be relabeled as layer metrics."
            ),
            "required_evidence": primary_tests,
        },
        {
            "section_id": "statistical_reliability",
            "label": "Statistical Reliability",
            "status": "insufficient_evidence",
            "reason": "No confidence intervals, fold variance, bootstrap result, or significance/stability test is published for this layer.",
            "required_evidence": ["confidence_interval", "fold_variance", "bootstrap_or_permutation_test", "sample_size_power_note"],
        },
        {
            "section_id": "calibration_distribution",
            "label": "Calibration / Distribution",
            "status": "insufficient_evidence",
            "reason": "No layer-aware calibration curve, distribution drift, embedding separation, or representation stability artifact is published.",
            "required_evidence": ["calibration_or_distribution_diagnostic", "drift_by_fold", "embedding_or_score_distribution"],
        },
        {
            "section_id": "signal_diagnostics",
            "label": "Signal Diagnostics",
            "status": "insufficient_evidence",
            "reason": "No feature importance, missingness, monotonicity, sensitivity, redundancy, or correlation diagnostic is published for this layer.",
            "required_evidence": ["feature_importance", "missingness", "sensitivity", "correlation_or_redundancy"],
        },
        {
            "section_id": "robustness",
            "label": "Robustness",
            "status": "insufficient_evidence",
            "reason": "No layer-specific slice robustness is published by regime, volatility, liquidity, target, sector, event context, or period.",
            "required_evidence": ["regime_slice", "volatility_slice", "liquidity_slice", "period_slice"],
        },
        {
            "section_id": "integrity",
            "label": "Integrity",
            "status": "published" if guardrail_metrics or has_artifact else "insufficient_evidence",
            "reason": (
                f"Normalized layer_evaluation_summary artifact is present with status {artifact_status}."
                if has_artifact
                else "No layer-specific leakage, label timing, point-in-time isolation, or artifact provenance check is published."
            ),
            "required_evidence": guardrail_tests or ["leakage_check", "label_timing_check", "train_test_isolation", "artifact_lineage"],
        },
        {
            "section_id": "downstream_contribution",
            "label": "Downstream Contribution",
            "status": "reference_only" if group_reference_available else "insufficient_evidence",
            "reason": (
                "A group-level baseline-active result is available, but no layer ablation or marginal contribution study isolates this layer."
                if group_reference_available
                else "No group-level result or layer ablation is available."
            ),
            "required_evidence": ["layer_ablation", "substitution_test", "marginal_group_metric_delta"],
        },
    ]
    return sections


def _layer_metric_families(layer: int) -> list[str]:
    families = []
    for test in LAYER_METRIC_TESTS[layer]:
        family = test["metric_family"]
        if family not in families:
            families.append(family)
    return families


def build_model_layer_evaluation_summary(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build layer-level model-evidence dossiers for the Models page."""

    generated_at_utc = generated_at_utc or now_utc()
    layer_payload = build_model_layer_readiness_summary(storage_root=storage_root, generated_at_utc=generated_at_utc)
    promotion_payload = build_model_promotion_posture_summary(storage_root=storage_root, generated_at_utc=generated_at_utc)
    layer_chart = _chart(layer_payload)
    promotion_chart = _chart(promotion_payload)
    lifecycle_by_layer = {
        int(layer["layer"]): layer
        for layer in layer_chart.get("layers", [])
        if isinstance(layer, Mapping) and isinstance(layer.get("layer"), int)
    }
    promotion_by_layer = {
        int(row["layer"]): row
        for row in promotion_chart.get("models", [])
        if isinstance(row, Mapping) and isinstance(row.get("layer"), int)
    }
    group_versions = [dict(row) for row in promotion_chart.get("group_versions", []) if isinstance(row, Mapping)]
    artifacts_by_layer = _load_layer_evaluation_artifacts(storage_root)
    rows = []
    evaluated_count = 0
    for layer, model_id, name in MODEL_LAYERS:
        lifecycle = lifecycle_by_layer.get(layer, {})
        promotion = promotion_by_layer.get(layer, {})
        versions = lifecycle.get("versions") if isinstance(lifecycle.get("versions"), list) else []
        version = versions[0] if versions and isinstance(versions[0], Mapping) else None
        claim = LAYER_EVALUATION_CLAIMS[layer]
        artifact = artifacts_by_layer.get(layer)
        sections = _layer_evaluation_sections(layer, version=version, group_versions=group_versions, artifact=artifact)
        missing_count = sum(1 for section in sections if section.get("status") == "insufficient_evidence")
        artifact_status = str((artifact or {}).get("evaluation_status") or "insufficient_evidence")
        validity_status = str((artifact or {}).get("validity_status") or artifact_status)
        if artifact_status not in {"insufficient_evidence", "not_published"}:
            evaluated_count += 1
        metric_lookup = _artifact_metric_lookup(
            item for item in (artifact or {}).get("metric_values", []) if isinstance(item, Mapping)
        )
        metric_tests = []
        for test in LAYER_METRIC_TESTS[layer]:
            metric = metric_lookup.get(test["metric_id"])
            metric_value = _mean_metric_value(metric.get("value")) if isinstance(metric, Mapping) else None
            test_status = str((metric or {}).get("status") or test["status"]) if isinstance(metric, Mapping) else test["status"]
            metric_tests.append({**test, "status": test_status, "metric_value": metric_value})
        rows.append(
            {
                "layer": layer,
                "layer_id": f"layer_{layer:02d}",
                "model_id": model_id,
                "name": name,
                "version_id": version.get("version_id") if isinstance(version, Mapping) else None,
                "evidence_status": artifact_status,
                "validity_status": validity_status,
                "validity_decision": {
                    "status": validity_status,
                    "reason": str((artifact or {}).get("validity_reason") or "No layer_evaluation_summary artifact with layer-specific metrics has been published yet."),
                    "missing_section_count": missing_count,
                },
                "claim": {
                    "modeling_claim": claim["claim"],
                    "target_definition": claim["target_definition"],
                    "input_scope": lifecycle.get("summary") or "",
                    "output_contract": f"{model_id} layer output consumed by downstream model stack.",
                },
                "metric_families": _layer_metric_families(layer),
                "metric_tests": metric_tests,
                "sections": sections,
                "evaluation_population": (artifact or {}).get("evaluation_population") or {},
                "metric_values": (artifact or {}).get("metric_values") or [],
                "parameter_values": (artifact or {}).get("parameter_values") or [],
                "runtime_coefficients": (artifact or {}).get("runtime_coefficients") or [],
                "artifact_ref": str(_layer_evaluation_artifact_path(storage_root, model_id)) if artifact else None,
                "source_artifact_refs": (artifact or {}).get("source_artifact_refs") or [],
                "group_context": {
                    "available": bool(group_versions),
                    "active_baseline_ref": group_versions[-1].get("version_id") if group_versions else None,
                    "note": "Group-level metrics are available only as context and are not layer-specific evidence.",
                },
                "operational_refs": {
                    "lifecycle_status": lifecycle.get("lifecycle_status") or lifecycle.get("status"),
                    "promotion_status": promotion.get("promotion_status"),
                    "blockers": promotion.get("blockers") or lifecycle.get("blockers") or [],
                    "latest_updated_at_utc": lifecycle.get("latest_updated_at_utc") or promotion.get("latest_updated_at_utc"),
                },
            }
        )
    missing_artifact_count = len(MODEL_LAYERS) - len(artifacts_by_layer)
    return {
        "contract_type": MODEL_LAYER_EVALUATION_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": "blocked" if missing_artifact_count or evaluated_count < len(MODEL_LAYERS) else "ready",
        "severity": "medium" if missing_artifact_count or evaluated_count < len(MODEL_LAYERS) else "info",
        "summary": f"Layer model evidence dossiers consume normalized layer_evaluation_summary artifacts; {evaluated_count} of {len(MODEL_LAYERS)} layers publish source evaluation evidence.",
        "chart_payload": {
            "layers": rows,
            "required_artifact": "layer_evaluation_summary",
            "artifact_status": {
                "artifact_count": len(artifacts_by_layer),
                "missing_artifact_count": missing_artifact_count,
                "evaluated_layer_count": evaluated_count,
            },
            "metric_family_descriptions": METRIC_FAMILY_DESCRIPTIONS,
            "model_group_supplemental_tests": MODEL_GROUP_SUPPLEMENTAL_TESTS,
            "state_vocabulary": ["evaluated", "evaluated_local_deferred", "evaluated_summary_mode", "published", "insufficient_evidence", "not_applicable", "failed_validity", "reference_only"],
        },
        "profile_refs": [{"registry_ref": "MODEL_LAYER_EVALUATION_SUMMARY", "field": "contract_type"}],
        "issue_refs": [
            {
                "issue_id": "missing_layer_evaluation_artifacts",
                "severity": "medium",
                "summary": "Some per-layer subtabs still lack source layer_evaluation_summary evidence with layer-specific statistical metrics.",
                "missing_artifact_count": missing_artifact_count,
                "evaluated_layer_count": evaluated_count,
            }
        ] if missing_artifact_count or evaluated_count < len(MODEL_LAYERS) else [],
        "diagnostic_refs": [],
        "lineage_refs": _source_refs(_read_latest(storage_root, HISTORICAL_TASK_PROGRESS_CONTRACT), _read_latest(storage_root, EXECUTION_RUNTIME_STATUS_CONTRACT)),
        "freshness": {"class": "derived_model_layer_evidence_summary", "status": "fresh", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
        "schema_ref": MODEL_LAYER_EVALUATION_SCHEMA_REF,
    }


def build_model_promotion_posture_summary(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build model promotion posture rows for the Models page."""

    generated_at_utc = generated_at_utc or now_utc()
    historical = _read_latest(storage_root, HISTORICAL_TASK_PROGRESS_CONTRACT)
    runtime = _read_latest(storage_root, EXECUTION_RUNTIME_STATUS_CONTRACT)
    tasks = _tasks(historical)
    evaluation_task = _global_task(tasks, "model_group.evaluation")
    promotion_task = _global_task(tasks, "model_group.promotion")
    active_ref = _active_ref(runtime)
    group_versions, excluded_group_versions = _model_group_promotion_evidence(storage_root, active_ref=active_ref)
    rows = []
    blocked_count = 0
    active_count = 0
    for layer, model_id, name in MODEL_LAYERS:
        layer_tasks = _layer_tasks(tasks, layer)
        version = _version_for_layer(layer, model_id, layer_tasks)
        blockers = _task_blockers(layer_tasks)
        is_active = _ref_matches_layer(active_ref, layer, model_id)
        promotion_status = _task_status(promotion_task) if promotion_task else "not_reviewed"
        if blockers:
            promotion_status = "blocked"
            blocked_count += 1
        if is_active:
            active_count += 1
        rows.append(
            {
                "layer": layer,
                "layer_id": f"layer_{layer:02d}",
                "model_id": model_id,
                "model_ref": version["version_id"] if version else model_id,
                "version_id": version["version_id"] if version else None,
                "model_name": name,
                "promotion_status": "active" if is_active else promotion_status,
                "activation_status": "active" if is_active else "not_active",
                "evaluation_status": _task_status(evaluation_task) if evaluation_task else "not_evaluated",
                "latest_agent_decision_status": None,
                "missing_evidence_categories": [] if version else ["registered_model_version"],
                "blockers": blockers,
                "latest_updated_at_utc": _latest_update(layer_tasks),
                "summary": f"{name} promotion posture derived from dashboard lifecycle evidence.",
            }
        )
    status_counts: dict[str, int] = {}
    for version in group_versions:
        status = str(version.get("decision_status") or "not_reported")
        status_counts[status] = status_counts.get(status, 0) + 1
    identity_counts: dict[str, int] = {}
    for version in group_versions:
        identity = str(version.get("identity") or "candidate")
        identity_counts[identity] = identity_counts.get(identity, 0) + 1
    return {
        "contract_type": MODEL_PROMOTION_POSTURE_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": "blocked" if blocked_count else "ready",
        "severity": "medium" if blocked_count else "info",
        "summary": (
            f"Model promotion posture has {len(group_versions)} valid scoped model-group promotion versions and {len(rows)} layer rows."
            if group_versions
            else "No valid scoped model-group promotion evidence is published."
        ),
        "chart_payload": {
            "models": rows,
            "group_versions": group_versions,
            "excluded_group_versions": excluded_group_versions,
            "status_counts": status_counts,
            "identity_counts": identity_counts,
        },
        "profile_refs": [{"registry_ref": "MODEL_PROMOTION_POSTURE_SUMMARY", "field": "contract_type"}],
        "issue_refs": _exclusion_issue_refs(excluded_group_versions),
        "diagnostic_refs": [],
        "lineage_refs": _source_refs(historical, runtime),
        "freshness": _freshness([historical, runtime]),
        "schema_ref": MODEL_PROMOTION_POSTURE_SCHEMA_REF,
    }


def refresh_model_layer_readiness_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    payload = build_model_layer_readiness_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=MODEL_LAYER_READINESS_CONTRACT)
    return _refresh_receipt(MODEL_LAYER_READINESS_CONTRACT, materialized.index_row)


def refresh_model_layer_evaluation_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    generated_at_utc = now_utc()
    materialize_layer_evaluation_summary_artifacts(storage_root=storage_root, generated_at_utc=generated_at_utc)
    payload = build_model_layer_evaluation_summary(storage_root=storage_root, generated_at_utc=generated_at_utc)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=MODEL_LAYER_EVALUATION_CONTRACT)
    return _refresh_receipt(MODEL_LAYER_EVALUATION_CONTRACT, materialized.index_row)


def refresh_model_promotion_posture_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    payload = build_model_promotion_posture_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=MODEL_PROMOTION_POSTURE_CONTRACT)
    return _refresh_receipt(MODEL_PROMOTION_POSTURE_CONTRACT, materialized.index_row)


def _refresh_receipt(contract_type: str, materialized: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": contract_type,
        "materialized": dict(materialized),
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


__all__ = [
    "LAYER_EVALUATION_SUMMARY_CONTRACT",
    "MODEL_LAYER_READINESS_CONTRACT",
    "MODEL_LAYER_EVALUATION_CONTRACT",
    "MODEL_PROMOTION_POSTURE_CONTRACT",
    "materialize_layer_evaluation_summary_artifacts",
    "build_model_layer_readiness_summary",
    "build_model_layer_evaluation_summary",
    "build_model_promotion_posture_summary",
    "refresh_model_layer_readiness_summary_read_model",
    "refresh_model_layer_evaluation_summary_read_model",
    "refresh_model_promotion_posture_summary_read_model",
]
