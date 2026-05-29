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
from typing import Any, Mapping

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

MODEL_LAYER_READINESS_CONTRACT = "model_layer_readiness_summary"
MODEL_PROMOTION_POSTURE_CONTRACT = "model_promotion_posture_summary"
MODEL_LAYER_READINESS_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_LAYER_READINESS_CONTRACT}.schema.json"
MODEL_PROMOTION_POSTURE_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_PROMOTION_POSTURE_CONTRACT}.schema.json"

HISTORICAL_TASK_PROGRESS_CONTRACT = "historical_task_progress_summary"
EXECUTION_RUNTIME_STATUS_CONTRACT = "execution_realtime_trading_runtime_status"
DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_STALE_AFTER_SECONDS = 900

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


def _version_for_layer(layer: int, model_id: str, layer_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    model_tasks = [task for task in layer_tasks if str(task.get("stage_type") or "") in {"model_generation", "model_task"} or "model" in str(task.get("task_id") or "")]
    materialized_tasks = [
        task for task in model_tasks
        if _task_status(task).lower() in {"running", "succeeded", "not_applicable"}
        or bool(_receipt_refs(task))
        or bool(task.get("started_at_utc"))
        or bool(task.get("ended_at_utc"))
    ]
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
        if exclusion_reasons:
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
        version_key = candidate_model_ref or fold_id or decision_path.parent.name
        version_label = _model_group_version_label(
            fold_id=fold_id,
            candidate_model_ref=candidate_model_ref,
            target_symbol=target_symbol,
            fallback=decision_path.parent.name,
        )
        if active_ref and candidate_model_ref and candidate_model_ref == active_ref:
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
    "MODEL_LAYER_READINESS_CONTRACT",
    "MODEL_PROMOTION_POSTURE_CONTRACT",
    "build_model_layer_readiness_summary",
    "build_model_promotion_posture_summary",
    "refresh_model_layer_readiness_summary_read_model",
    "refresh_model_promotion_posture_summary_read_model",
]
