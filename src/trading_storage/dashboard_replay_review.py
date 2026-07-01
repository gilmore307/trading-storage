"""Replay review dashboard read-model producer.

The producer projects already-materialized post-replay review artifacts into a
small owner-facing read model for the dashboard replay pages. It does not run
replay, review models, activate models, call providers, submit broker work, or
mutate account state.
"""

from __future__ import annotations

import json
import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

MODEL_GROUP_REPLAY_REVIEW_CONTRACT = "model_group_replay_review_summary"
MODEL_GROUP_REPLAY_REVIEW_SCHEMA_REF = (
    f"storage/06_dashboard_cache/schemas/{MODEL_GROUP_REPLAY_REVIEW_CONTRACT}.schema.json"
)
DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_REPLAY_ROOT = Path("05_replay_datasets") / "promotion_replay_candidate_policy"
DEFAULT_STALE_AFTER_SECONDS = 900
MAX_REVIEW_RUNS = 50
MAX_SAMPLE_ROWS = 5
MAX_LAYER_DECISION_ROWS = 250
CURRENT_MODEL_WORKER_FOLD_RE = re.compile(r"^fold_[a-z0-9]+_20\d{2}$")
REPLAY_DECISION_LAYER_IDS = (
    "model_01_background_context",
    "model_02_target_state",
    "model_03_event_state",
    "model_04_unified_decision",
    "model_05_option_expression",
)
EXCLUDED_REPLAY_DECISION_LAYER_IDS = ("model_06_residual_event_governance",)
REPLAY_OPERATION_COMPONENTS = (
    ("component_01_intake", "C01 Intake"),
    ("component_02_entry", "C02 Entry"),
    ("component_03_lifecycle", "C03 Lifecycle"),
    ("component_04_option_review", "C04 Option Review"),
    ("component_05_order_intent", "C05 Order Intent"),
    ("component_06_execution_gate", "C06 Execution Gate"),
    ("component_07_failure_review", "C07 Failure Review"),
)
REPLAY_OPERATION_COMPONENT_ALIASES = {
    "component_01_intake": "component_01_intake",
    "component_02_entry": "component_02_entry",
    "component_03_lifecycle": "component_03_lifecycle",
    "component_04_option_review": "component_04_option_review",
    "component_04_expression_review": "component_04_option_review",
    "component_05_order_intent": "component_05_order_intent",
    "component_06_execution_gate": "component_06_execution_gate",
    "component_07_failure_review": "component_07_failure_review",
    "c01_intake_operation": "component_01_intake",
    "c02_entry_operation": "component_02_entry",
    "c03_lifecycle_operation": "component_03_lifecycle",
    "c04_expression_review_operation": "component_04_option_review",
    "c04_option_review_operation": "component_04_option_review",
    "c05_order_intent_operation": "component_05_order_intent",
    "c06_execution_gate_operation": "component_06_execution_gate",
    "c07_failure_review_operation": "component_07_failure_review",
    "component_01_intake_operation": "component_01_intake",
    "component_02_entry_operation": "component_02_entry",
    "component_03_lifecycle_operation": "component_03_lifecycle",
    "component_04_expression_review_operation": "component_04_option_review",
    "component_05_order_intent_operation": "component_05_order_intent",
    "component_06_execution_gate_operation": "component_06_execution_gate",
    "component_07_failure_review_operation": "component_07_failure_review",
}
REPLAY_OPERATION_COMPONENT_LABELS = dict(REPLAY_OPERATION_COMPONENTS)
REPLAY_DECISION_LAYER_LABELS = {
    "model_01_background_context": "M01 Background Context",
    "model_02_target_state": "M02 Target State",
    "model_03_event_state": "M03 Event State",
    "model_04_unified_decision": "M04 Unified Decision",
    "model_05_option_expression": "M05 Option Expression",
    "model_06_residual_event_governance": "M06 Residual Event Governance",
}
REPLAY_DECISION_LAYER_ALIASES = {
    "m01": "model_01_background_context",
    "model_01": "model_01_background_context",
    "model_01_background_context": "model_01_background_context",
    "m02": "model_02_target_state",
    "model_02": "model_02_target_state",
    "model_02_target_state": "model_02_target_state",
    "m03": "model_03_event_state",
    "model_03": "model_03_event_state",
    "model_03_event_state": "model_03_event_state",
    "m04": "model_04_unified_decision",
    "model_04": "model_04_unified_decision",
    "model_04_unified_decision": "model_04_unified_decision",
    "m05": "model_05_option_expression",
    "model_05": "model_05_option_expression",
    "model_05_option_expression": "model_05_option_expression",
    "m06": "model_06_residual_event_governance",
    "model_06": "model_06_residual_event_governance",
    "model_06_residual_event_governance": "model_06_residual_event_governance",
}
PASSIVE_BASELINE_ACTIONS = {"baseline_action", "no_trade", "avoid_trade", "hold_cash"}
UNSCORED_LAYER_TRACE_STATUS = "effective_trace_unscored"


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            yield dict(payload)


def _coerce_csv_value(value: str | None) -> Any:
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "":
        return None
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if re.fullmatch(r"[-+]?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", stripped) or re.fullmatch(
            r"[-+]?\d+[eE][-+]?\d+",
            stripped,
        ):
            return float(stripped)
    except ValueError:
        return stripped
    return stripped


def _read_csv_records(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [
                {str(key): _coerce_csv_value(value) for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]
    except OSError:
        return []


def _count_by(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "not_reported")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _numeric_mean(rows: list[Mapping[str, Any]], field: str) -> float | None:
    values = [row.get(field) for row in rows]
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 10)


def _numeric_mean_by(rows: Iterable[Mapping[str, Any]], getter: Any) -> float | None:
    numeric = [value for row in rows if isinstance((value := getter(row)), (int, float))]
    if not numeric:
        return None
    return round(sum(float(value) for value in numeric) / len(numeric), 10)


def _safe_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 10)


def _normalized_layer_id(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized in {"none", "not_reported", "not_applicable"}:
        return None
    return REPLAY_DECISION_LAYER_ALIASES.get(normalized)


def _row_layer_id(row: Mapping[str, Any]) -> str | None:
    layer_attribution = row.get("layer_attribution")
    candidates = [
        row.get("effective_layer_id"),
        row.get("layer_id"),
        row.get("model_layer"),
        row.get("miss_attribution_layer"),
    ]
    if isinstance(layer_attribution, Mapping):
        candidates.extend(
            [
                layer_attribution.get("effective_layer_id"),
                layer_attribution.get("layer_id"),
                layer_attribution.get("model_layer"),
                layer_attribution.get("miss_attribution_layer"),
            ]
        )
    for candidate in candidates:
        layer_id = _normalized_layer_id(candidate)
        if layer_id:
            return layer_id
    return None


def _correctness_class(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("correctness_class") or "").strip().lower()
    if explicit in {"correct", "incorrect", "indeterminate", "not_applicable"}:
        return explicit
    chosen = str(row.get("chosen_action") or "").strip()
    best = str(row.get("best_available_action_by_future_outcome") or "").strip()
    regret = _safe_number(row.get("regret_to_best_available"))
    if regret is not None:
        return "correct" if regret == 0 else "incorrect"
    if chosen and best:
        return "correct" if chosen == best else "incorrect"
    return "indeterminate"


def _acceptability_class(correctness_class: str) -> str:
    if correctness_class == "correct":
        return "acceptable"
    if correctness_class == "incorrect":
        return "unacceptable"
    return "indeterminate"


def _review_regret_value(row: Mapping[str, Any]) -> float | None:
    regret = _safe_number(row.get("regret_to_best_available"))
    if regret is not None:
        return regret
    impact = _safe_number(row.get("impact_normalized_severity_score"))
    if impact is not None:
        return impact
    if _correctness_class(row) == "correct":
        return 0.0
    return None


def _review_impact_value(row: Mapping[str, Any]) -> float | None:
    impact = _safe_number(row.get("impact_normalized_severity_score"))
    if impact is not None:
        return impact
    regret = _safe_number(row.get("regret_to_best_available"))
    if regret is not None:
        return regret
    if _correctness_class(row) == "correct":
        return 0.0
    return None


def _source_decision_id(row: Mapping[str, Any], *, fallback_index: int | None = None) -> str:
    value = str(row.get("source_decision_id") or row.get("decision_id") or row.get("replay_decision_id") or "").strip()
    if value:
        return value
    return f"decision_row_{fallback_index}" if fallback_index is not None else ""


def _decision_time(row: Mapping[str, Any]) -> Any:
    return row.get("decision_time") or row.get("timestamp") or row.get("replay_time_pointer")


def _target_symbol(row: Mapping[str, Any]) -> Any:
    return row.get("target_symbol") or row.get("target_ref")


def _layer_diagnostics(row: Mapping[str, Any], layer_id: str) -> Mapping[str, Any]:
    diagnostics = row.get("model_layer_diagnostics")
    if not isinstance(diagnostics, Mapping):
        return {}
    value = diagnostics.get(layer_id)
    return value if isinstance(value, Mapping) else {}


def _layer_ref(row: Mapping[str, Any], layer_id: str) -> Any:
    refs = row.get("model_layer_refs")
    if isinstance(refs, Mapping):
        return refs.get(layer_id)
    return None


def _effective_layer_decision(row: Mapping[str, Any], layer_id: str, diagnostics: Mapping[str, Any]) -> str:
    if layer_id == "model_01_background_context":
        state_quality = diagnostics.get("state_quality_score")
        risk = diagnostics.get("market_risk_stress_score")
        return f"background_context_state quality={state_quality} risk={risk}"
    if layer_id == "model_02_target_state":
        target = diagnostics.get("target_ref") or _target_symbol(row)
        direction = diagnostics.get("target_direction_score_1D")
        tradability = diagnostics.get("tradability_score_1D")
        return f"selected_target {target} direction_1d={direction} tradability_1d={tradability}"
    if layer_id == "model_03_event_state":
        uncertainty = diagnostics.get("event_uncertainty_score_1D")
        block = diagnostics.get("event_entry_block_pressure_score_1D")
        return f"event_state uncertainty_1d={uncertainty} block_pressure_1d={block}"
    if layer_id == "model_04_unified_decision":
        return str(
            diagnostics.get("resolved_underlying_action_type")
            or diagnostics.get("resolved_action_side")
            or row.get("decision_action")
            or row.get("action")
            or "not_reported"
        )
    if layer_id == "model_05_option_expression":
        expression = diagnostics.get("selected_expression_type") or row.get("selected_option_expression_type")
        contract = diagnostics.get("selected_contract_ref") or row.get("selected_option_contract_ref") or row.get("instrument_ref")
        return f"{expression or 'not_reported'} {contract or ''}".strip()
    return "not_reported"


def _scored_layer_overlay(row: Mapping[str, Any], layer_id: str) -> dict[str, Any]:
    if layer_id == "model_04_unified_decision":
        chosen = _effective_layer_decision(row, layer_id, _layer_diagnostics(row, layer_id))
        realized_value = row.get("directional_underlying_return")
        if realized_value is None:
            realized_value = row.get("underlying_return")
        realized_return = _safe_number(realized_value)
        if realized_return is None:
            return {}
        baseline_return = _safe_number(row.get("baseline_return")) or 0.0
        best = chosen if realized_return >= baseline_return else "baseline_action"
        regret = round(max(0.0, baseline_return - realized_return), 10)
        return {
            "available_action": [chosen, "baseline_action"],
            "chosen_action": chosen,
            "best_available_action_by_future_outcome": best,
            "chosen_action_return": realized_return,
            "best_available_action_return": realized_return if best == chosen else baseline_return,
            "regret_to_best_available": regret,
            "correctness_class": "correct" if regret == 0 else "incorrect",
            "classification_basis": "derived_from_underlying_directional_return_label",
        }
    if layer_id == "model_05_option_expression":
        fill_status = str(row.get("fill_status") or "")
        decision_status = str(row.get("decision_status") or "")
        filled = fill_status == "simulated_filled" or decision_status in {"filled", "approved", "executed"}
        if not filled:
            return {}
        chosen = str(row.get("chosen_action") or row.get("decision_action") or row.get("action") or "take_trade")
        realized_return = _safe_number(row.get("realized_return"))
        if realized_return is None:
            return {}
        baseline_return = _safe_number(row.get("baseline_return")) or 0.0
        best = chosen if realized_return >= baseline_return else "baseline_action"
        regret = round(max(0.0, baseline_return - realized_return), 10)
        return {
            "available_action": [chosen, "baseline_action"],
            "chosen_action": chosen,
            "best_available_action_by_future_outcome": best,
            "chosen_action_return": realized_return,
            "best_available_action_return": realized_return if best == chosen else baseline_return,
            "regret_to_best_available": regret,
            "correctness_class": "correct" if regret == 0 else "incorrect",
            "classification_basis": "derived_from_selected_option_realized_return_label",
        }
    return {}


def _review_rows_by_source_and_layer(review_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in review_rows:
        source_id = _source_decision_id(row)
        layer_id = _row_layer_id(row)
        if source_id and layer_id in REPLAY_DECISION_LAYER_IDS:
            indexed[(source_id, layer_id)] = row
    return indexed


def _best_available_action(row: Mapping[str, Any]) -> str:
    return str(row.get("best_available_action_by_future_outcome") or "").strip()


def _is_harmful_error(row: Mapping[str, Any], correctness_class: str) -> bool:
    if correctness_class != "incorrect":
        return False
    best = _best_available_action(row).lower()
    if best in PASSIVE_BASELINE_ACTIONS:
        return True
    failure_type = str(row.get("failure_type") or "").strip().lower()
    return failure_type not in {"", "none", "not_failed"}


def _is_missed_good(row: Mapping[str, Any], correctness_class: str) -> bool:
    best = _best_available_action(row).lower()
    return correctness_class == "incorrect" and bool(best) and best not in PASSIVE_BASELINE_ACTIONS


def _latest_dirs(root: Path, pattern: str, limit: int) -> list[Path]:
    try:
        dirs = [path for path in root.glob(pattern) if path.is_dir()]
    except OSError:
        return []
    return sorted(dirs, key=lambda path: path.name)[-limit:]


def _review_run_sort_value(summary: Mapping[str, Any]) -> str:
    return str(summary.get("completed_at_utc") or summary.get("created_at_utc") or summary.get("review_run_id") or "")


def _latest_review_run_per_fold(review_runs: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    latest_by_fold: dict[str, dict[str, Any]] = {}
    superseded_count = 0
    for run in review_runs:
        fold_id = str(run.get("candidate_fold_id") or "").strip()
        if not fold_id:
            continue
        current = latest_by_fold.get(fold_id)
        if current is None:
            latest_by_fold[fold_id] = run
            continue
        superseded_count += 1
        if _review_run_sort_value(run) >= _review_run_sort_value(current):
            latest_by_fold[fold_id] = run
    return (
        sorted(latest_by_fold.values(), key=lambda run: (str(run.get("candidate_fold_id") or ""), _review_run_sort_value(run))),
        superseded_count,
    )


def _current_model_worker_fold_id(value: object) -> str:
    fold_id = str(value or "").strip().lower()
    return fold_id if CURRENT_MODEL_WORKER_FOLD_RE.fullmatch(fold_id) else ""


def _current_replay_scope(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        return {
            "include": False,
            "reason_code": "missing_receipt",
            "reason": "replay artifact does not publish a receipt",
        }
    candidate_fold_id = _current_model_worker_fold_id(receipt.get("candidate_fold_id") or receipt.get("fold_id"))
    if not candidate_fold_id:
        return {
            "include": False,
            "reason_code": "stale_replay_fold_id",
            "reason": "replay artifact does not use current fold_<target>_<year> naming",
        }
    if not str(receipt.get("candidate_training_target") or receipt.get("target_symbol") or "").strip():
        return {
            "include": False,
            "reason_code": "missing_target_scope",
            "reason": "replay artifact does not declare its target scope",
        }
    return {"include": True, "candidate_fold_id": candidate_fold_id}


def _compact_decision_scope(summary: Mapping[str, Any]) -> dict[str, Any]:
    decision_scope = summary.get("decision_scope")
    if not isinstance(decision_scope, Mapping):
        return {}
    return {
        "decision_row_count": decision_scope.get("decision_row_count"),
        "filled_count": decision_scope.get("filled_count"),
        "selected_target_count": decision_scope.get("selected_target_count"),
        "selected_timestamp_count": decision_scope.get("selected_timestamp_count"),
        "decision_status_counts": decision_scope.get("decision_status_counts") or {},
        "fill_status_counts": decision_scope.get("fill_status_counts") or {},
        "selection_concentration_status": decision_scope.get("selection_concentration_status"),
    }


def _compact_performance_summary(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        return {}
    return {
        "decision_scope": _compact_decision_scope(summary),
        "target_performance": dict(summary.get("target_performance") or {})
        if isinstance(summary.get("target_performance"), Mapping)
        else {},
        "stock_selection": dict(summary.get("stock_selection") or {})
        if isinstance(summary.get("stock_selection"), Mapping)
        else {},
        "direction_expression": dict(summary.get("direction_expression") or {})
        if isinstance(summary.get("direction_expression"), Mapping)
        else {},
        "option_expression": dict(summary.get("option_expression") or {})
        if isinstance(summary.get("option_expression"), Mapping)
        else {},
        "replacement_review": {
            key: value
            for key, value in dict(summary.get("replacement_review") or {}).items()
            if not key.endswith("_sample")
        }
        if isinstance(summary.get("replacement_review"), Mapping)
        else {},
        "layer_differentiation": dict(summary.get("layer_differentiation") or {})
        if isinstance(summary.get("layer_differentiation"), Mapping)
        else {},
    }


def _sample_review_row(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "review_id",
        "decision_time",
        "target_symbol",
        "replay_month",
        "chosen_action",
        "available_action",
        "best_available_action_by_future_outcome",
        "chosen_action_return",
        "best_available_action_return",
        "regret_to_best_available",
        "cause_family",
        "failure_type",
        "first_gap_component",
        "first_gap_mechanism",
        "miss_attribution_layer",
        "impact_normalized_severity_score",
        "review_status",
    )
    sampled = {field: row.get(field) for field in fields if field in row}
    sampled["regret_to_best_available"] = _review_regret_value(row)
    sampled["impact_normalized_severity_score"] = _review_impact_value(row)
    return sampled


def _review_rows_summary(rows_path: Path | None) -> dict[str, Any]:
    rows = list(_iter_jsonl(rows_path)) if rows_path else []
    return {
        "row_count": len(rows),
        "cause_family_counts": _count_by(rows, "cause_family"),
        "failure_type_counts": _count_by(rows, "failure_type"),
        "first_gap_component_counts": _count_by(rows, "first_gap_component"),
        "miss_attribution_layer_counts": _count_by(rows, "miss_attribution_layer"),
        "review_status_counts": _count_by(rows, "review_status"),
        "mean_regret_to_best_available": _numeric_mean_by(rows, _review_regret_value),
        "mean_impact_normalized_severity_score": _numeric_mean_by(rows, _review_impact_value),
        "regret_value_count": sum(1 for row in rows if _review_regret_value(row) is not None),
        "impact_value_count": sum(1 for row in rows if _review_impact_value(row) is not None),
        "missing_regret_value_count": sum(1 for row in rows if _review_regret_value(row) is None),
        "missing_impact_value_count": sum(1 for row in rows if _review_impact_value(row) is None),
        "sample_rows": [_sample_review_row(row) for row in rows[:MAX_SAMPLE_ROWS]],
    }


def _json_digest(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _read_report_summary(path: Path) -> dict[str, Any]:
    report = _read_json_object(path)
    summary = report.get("summary") if isinstance(report, Mapping) else None
    return dict(summary) if isinstance(summary, Mapping) else {}


def _top_csv_rows(rows: list[dict[str, Any]], *, sort_field: str | None = None, limit: int = MAX_SAMPLE_ROWS) -> list[dict[str, Any]]:
    if sort_field is None:
        return rows[:limit]
    return sorted(
        rows,
        key=lambda row: _safe_number(row.get(sort_field)) if _safe_number(row.get(sort_field)) is not None else float("-inf"),
        reverse=True,
    )[:limit]


def _candidate_funnel_from_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    scored = int(_safe_number(summary.get("scored_candidate_row_count")) or 0)
    selected = int(_safe_number(summary.get("selected_candidate_row_count")) or 0)
    top10 = int(_safe_number(summary.get("selected_candidate_top_10_same_timestamp_count")) or 0)
    top25 = int(_safe_number(summary.get("selected_candidate_top_25_same_timestamp_count")) or 0)
    unexecutable = sum(
        int(_safe_number(value) or 0)
        for value in dict(summary.get("option_expression_unexecutable_reason_counts") or {}).values()
    )
    return {
        "scored_candidate_row_count": scored,
        "selected_candidate_row_count": selected,
        "option_expression_unexecutable_count": unexecutable,
        "selected_candidate_rank_mean_same_timestamp": summary.get("selected_candidate_rank_mean_same_timestamp"),
        "selected_candidate_top_10_same_timestamp_count": top10,
        "selected_candidate_top_25_same_timestamp_count": top25,
        "selected_candidate_outside_top_25_same_timestamp_count": summary.get(
            "selected_candidate_outside_top_25_same_timestamp_count"
        ),
        "selected_rate": _rate(selected, scored),
        "top_10_share_of_selected": _rate(top10, selected),
        "top_25_share_of_selected": _rate(top25, selected),
        "status_counts": summary.get("status_counts") or {},
        "option_expression_unexecutable_reason_counts": summary.get("option_expression_unexecutable_reason_counts") or {},
        "option_hard_filter_reason_counts": summary.get("option_hard_filter_reason_counts") or {},
        "future_outcome_label_included": bool(summary.get("future_outcome_label_included")),
        "summary_role": summary.get("summary_role"),
    }


def _option_expression_breakdown_summary(
    *,
    mechanics_rows: list[dict[str, Any]],
    dte_rows: list[dict[str, Any]],
    hard_filter_rows: list[dict[str, Any]],
    mechanism_summary: Mapping[str, Any],
) -> dict[str, Any]:
    filled_rows = [row for row in mechanics_rows if int(_safe_number(row.get("filled_count")) or 0) > 0]
    blocked_rows = [row for row in mechanics_rows if int(_safe_number(row.get("row_count")) or 0) > 0 and not int(_safe_number(row.get("filled_count")) or 0)]
    return {
        "m05_selection_state_count": len(mechanics_rows),
        "filled_selection_state_count": len(filled_rows),
        "blocked_selection_state_count": len(blocked_rows),
        "filled_count": sum(int(_safe_number(row.get("filled_count")) or 0) for row in mechanics_rows),
        "filled_good_count": sum(int(_safe_number(row.get("filled_good_count")) or 0) for row in mechanics_rows),
        "filled_bad_count": sum(int(_safe_number(row.get("filled_bad_count")) or 0) for row in mechanics_rows),
        "net_return_total": round(
            sum(float(_safe_number(row.get("net_return_total")) or 0.0) for row in mechanics_rows),
            10,
        ),
        "primary_filter_reason_counts": _count_by(
            [row for row in mechanics_rows if row.get("primary_filter_reason") is not None],
            "primary_filter_reason",
        ),
        "dte_policy_status_counts": _count_by(dte_rows, "diagnostic_status"),
        "hard_filter_overlap_group_count": len(hard_filter_rows),
        "mechanism_flags": mechanism_summary.get("flags") or [],
        "mechanism_fault_surface": mechanism_summary.get("fault_surface"),
        "top_mechanics_rows": _top_csv_rows(mechanics_rows, sort_field="row_count", limit=5),
        "top_dte_sensitivity_rows": _top_csv_rows(dte_rows, sort_field="row_count", limit=5),
        "top_hard_filter_overlap_rows": _top_csv_rows(hard_filter_rows, sort_field="row_count", limit=5),
    }


def _mechanism_contract_summary(rows: list[dict[str, Any]], report_summary: Mapping[str, Any]) -> dict[str, Any]:
    breached = [row for row in rows if str(row.get("breach_status") or "") == "breached"]
    critical = [row for row in breached if str(row.get("severity") or "") == "critical"]
    return {
        "mechanism_contract_count": report_summary.get("mechanism_contract_count") or len(rows),
        "breach_status_counts": report_summary.get("breach_status_counts") or _count_by(rows, "breach_status"),
        "component_counts": report_summary.get("component_counts") or _count_by(rows, "operation_component_id"),
        "breached_count": len(breached),
        "critical_breached_count": len(critical),
        "top_breaches": [
            {
                "mechanism_contract_id": row.get("mechanism_contract_id"),
                "operation_component_id": row.get("operation_component_id"),
                "runtime_component_ref": row.get("runtime_component_ref"),
                "severity": row.get("severity"),
                "breach_statement": row.get("breach_statement"),
                "acceptance_gate": row.get("acceptance_gate"),
            }
            for row in breached[:5]
        ],
        "fixed_input_only": bool(report_summary.get("fixed_input_only", True)),
    }


def _standard_review_diagnostics(layer_root: Path) -> dict[str, Any]:
    candidate_summary = _read_report_summary(layer_root / "model_candidate_selection_summary_report.json")
    pre_option_summary = _read_report_summary(layer_root / "pre_option_candidate_quality_report.json")
    mechanism_report_summary = _read_report_summary(layer_root / "operation_mechanism_contract_packet.json")
    mechanism_rows = _read_csv_records(layer_root / "operation_mechanism_contract_packet.csv")
    mechanics_rows = _read_csv_records(layer_root / "m05_selection_mechanics.csv")
    dte_rows = _read_csv_records(layer_root / "m05_dte_policy_sensitivity.csv")
    hard_filter_rows = _read_csv_records(layer_root / "m05_hard_filter_overlap.csv")
    m04_m05_summary = _read_report_summary(layer_root / "m04_m05_mechanism_review_report.json")
    source_gap_codes: list[str] = []
    if not candidate_summary:
        source_gap_codes.append("missing_model_candidate_selection_summary")
    if not mechanism_rows:
        source_gap_codes.append("missing_operation_mechanism_contract_rows")
    if not mechanics_rows:
        source_gap_codes.append("missing_m05_selection_mechanics_rows")
    return {
        "contract_version": 1,
        "status": "ready" if not source_gap_codes else "partial",
        "source_gap_codes": source_gap_codes,
        "candidate_entry_funnel": _candidate_funnel_from_summary(candidate_summary),
        "pre_option_candidate_quality": {
            "cohort_count": pre_option_summary.get("cohort_count"),
            "entry_intent_global_percentile_mean": pre_option_summary.get("entry_intent_global_percentile_mean"),
            "no_entry_global_percentile_mean": pre_option_summary.get("no_entry_global_percentile_mean"),
            "top25_global_percentile_mean": pre_option_summary.get("top25_global_percentile_mean"),
            "flags": pre_option_summary.get("flags") or [],
            "fixed_input_only": bool(pre_option_summary.get("fixed_input_only", True)),
        },
        "operation_mechanism_contracts": _mechanism_contract_summary(mechanism_rows, mechanism_report_summary),
        "option_expression_breakdown": _option_expression_breakdown_summary(
            mechanics_rows=mechanics_rows,
            dte_rows=dte_rows,
            hard_filter_rows=hard_filter_rows,
            mechanism_summary=m04_m05_summary,
        ),
        "classification_policy": {
            "model_groups_role": "model integrity and duplicate-output risk only; trading impact belongs to replay pages",
            "performance_role": "aggregate economic impact of funnel, duplicate, and option-expression mechanisms",
            "decisions_role": "M01-M05 layer decision correctness and duplicate decision traces",
            "operations_role": "C01-C07 machinery flow, block reasons, option materialization, and execution mechanics",
            "hindsight_caution": "Future returns, best-available choices, realized returns, and regret are post-replay labels, not decision-time inputs.",
        },
    }


def _normalized_operation_component_id(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return REPLAY_OPERATION_COMPONENT_ALIASES.get(text)


def _operation_component_id_from_row(row: Mapping[str, Any]) -> str | None:
    for field in ("runtime_component_ref", "operation_component_id", "component_id"):
        component_id = _normalized_operation_component_id(row.get(field))
        if component_id:
            return component_id
    return None


def _split_csv_list(value: object) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _first_present(*values: object) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _operation_numeric_mean(rows: list[Mapping[str, Any]], field: str) -> float | None:
    return _numeric_mean_by(rows, lambda row: _safe_number(row.get(field)))


def _sample_operation_metric_row(row: Mapping[str, Any], component_id: str) -> dict[str, Any]:
    fields = (
        "component_index",
        "operation_component_id",
        "runtime_component_ref",
        "operation_component_label",
        "metric_family",
        "metric_name",
        "metric_scope",
        "analysis_method",
        "evidence_role",
        "label_role",
        "required_evidence_status",
        "availability_status",
        "reason_codes",
        "row_count",
        "eligible_row_count",
        "selected_count",
        "selected_target_present_count",
        "selected_forward_return_mean",
        "selected_forward_return_rank_mean",
        "selected_forward_return_percentile_mean",
        "top_quartile_hit_rate",
        "opportunity_cost_to_best_mean",
        "opportunity_cost_to_median_mean",
        "value",
        "diagnostic_only",
    )
    sampled = {field: row.get(field) for field in fields if field in row}
    sampled["component_id"] = component_id
    sampled["component_label"] = REPLAY_OPERATION_COMPONENT_LABELS[component_id]
    return sampled


def _sample_operation_action_row(row: Mapping[str, Any], component_id: str) -> dict[str, Any]:
    fields = (
        "operation_action_row_id",
        "source_decision_id",
        "source_decision_index",
        "decision_time",
        "replay_month",
        "target_symbol",
        "operation_component_id",
        "runtime_component_ref",
        "operation_component_label",
        "component_index",
        "operation_action",
        "operation_status",
        "input_ref",
        "input_summary",
        "output_ref",
        "output_summary",
        "block_reason",
        "analysis_method",
        "evidence_role",
        "label_role",
        "trigger_state",
        "pit_feasible_action_set_ref",
        "pit_feasible_action_count",
        "pit_feasible_action_set_status",
        "component_objective",
        "chosen_action",
        "best_available_action_by_future_outcome",
        "chosen_action_return",
        "best_available_action_return",
        "chosen_rank_ex_post",
        "component_correctness_class",
        "post_replay_label_basis",
        "decision_time_evidence_fields",
        "post_replay_label_fields",
        "realized_return",
        "regret_to_best_available",
        "impact_normalized_severity_score",
        "review_status",
    )
    sampled = {field: row.get(field) for field in fields if field in row}
    sampled["component_id"] = component_id
    sampled["component_label"] = REPLAY_OPERATION_COMPONENT_LABELS[component_id]
    return sampled


def _replay_operations_c01_c07_summary(layer_root: Path) -> dict[str, Any]:
    flow_rows = _read_csv_records(layer_root / "operation_component_flow.csv")
    packet_rows = _read_csv_records(layer_root / "operation_component_review_packet.csv")
    metric_rows = _read_csv_records(layer_root / "operation_component_metrics.csv")
    action_rows = _read_csv_records(layer_root / "operation_component_action_rows.csv")
    source_gap_codes: list[str] = []
    if not flow_rows:
        source_gap_codes.append("missing_operation_component_flow")
    if not packet_rows:
        source_gap_codes.append("missing_operation_component_review_packet")
    if not metric_rows:
        source_gap_codes.append("missing_operation_component_metrics")
    if not action_rows:
        source_gap_codes.append("missing_operation_component_action_rows")

    flow_by_component = {
        component_id: row
        for row in flow_rows
        if (component_id := _operation_component_id_from_row(row)) is not None
    }
    packet_by_component = {
        component_id: row
        for row in packet_rows
        if (component_id := _operation_component_id_from_row(row)) is not None
    }
    metrics_by_component: dict[str, list[dict[str, Any]]] = {component_id: [] for component_id, _ in REPLAY_OPERATION_COMPONENTS}
    for row in metric_rows:
        component_id = _operation_component_id_from_row(row)
        if component_id:
            metrics_by_component.setdefault(component_id, []).append(dict(row))
    actions_by_component: dict[str, list[dict[str, Any]]] = {component_id: [] for component_id, _ in REPLAY_OPERATION_COMPONENTS}
    for row in action_rows:
        component_id = _operation_component_id_from_row(row)
        if component_id:
            actions_by_component.setdefault(component_id, []).append(dict(row))

    component_summary: dict[str, dict[str, Any]] = {}
    component_metric_rows: list[dict[str, Any]] = []
    component_action_rows: list[dict[str, Any]] = []
    for component_id, component_label in REPLAY_OPERATION_COMPONENTS:
        flow = flow_by_component.get(component_id, {})
        packet = packet_by_component.get(component_id, {})
        metrics = metrics_by_component.get(component_id, [])
        actions = actions_by_component.get(component_id, [])
        availability_counts = _count_by(metrics, "availability_status")
        data_gap_metric_count = int(availability_counts.get("data_gap", 0))
        computed_metric_count = int(availability_counts.get("computed", 0))
        not_applicable_metric_count = int(availability_counts.get("not_applicable", 0))
        metric_family_counts = _count_by(metrics, "metric_family")
        analysis_method_counts = _count_by(metrics, "analysis_method")
        required_evidence_status_counts = _count_by(metrics, "required_evidence_status")
        metric_rows_returned = [
            _sample_operation_metric_row(row, component_id)
            for row in metrics[:MAX_SAMPLE_ROWS]
        ]
        component_metric_rows.extend(metric_rows_returned)
        action_rows_returned = [
            _sample_operation_action_row(row, component_id)
            for row in actions[:MAX_LAYER_DECISION_ROWS]
        ]
        component_action_rows.extend(action_rows_returned)
        input_count = _first_present(flow.get("input_count"), packet.get("input_count"))
        output_count = _first_present(flow.get("output_count"), packet.get("output_count"))
        eligible_count = _first_present(flow.get("settled_metric_eligible_count"), packet.get("settled_metric_eligible_count"))
        first_limiting_count = _first_present(flow.get("first_limiting_projection_count"), packet.get("first_limiting_projection_count"))
        missing_outputs = _split_csv_list(packet.get("missing_review_outputs"))
        component_gaps: list[str] = []
        if component_id not in flow_by_component:
            component_gaps.append("missing_operation_component_flow_row")
        if component_id not in packet_by_component:
            component_gaps.append("missing_operation_component_review_packet_row")
        if not metrics:
            component_gaps.append("missing_operation_component_metric_rows")
        if not actions:
            component_gaps.append("missing_operation_component_action_rows")
        if data_gap_metric_count:
            component_gaps.append("operation_component_metric_data_gap")
        component_summary[component_id] = {
            "component_id": component_id,
            "component_label": component_label,
            "component_index": _first_present(flow.get("component_index"), packet.get("component_index")),
            "runtime_component_ref": _first_present(flow.get("runtime_component_ref"), packet.get("runtime_component_ref")),
            "operation_component_id": _first_present(flow.get("operation_component_id"), packet.get("operation_component_id")),
            "operation_role": _first_present(flow.get("operation_role"), packet.get("operation_role")),
            "applicability_status": _first_present(flow.get("applicability_status"), packet.get("applicability_status")),
            "input_count": input_count,
            "output_count": output_count,
            "dropped_or_blocked_count": _first_present(flow.get("dropped_or_blocked_count"), packet.get("dropped_or_blocked_count")),
            "censored_count": flow.get("censored_count"),
            "settled_metric_eligible_count": eligible_count,
            "settled_metric_excluded_count": flow.get("settled_metric_excluded_count"),
            "first_limiting_projection_count": first_limiting_count,
            "first_limiting_projections": _split_csv_list(flow.get("first_limiting_projections")),
            "review_projection_refs": _split_csv_list(flow.get("review_projection_refs") or packet.get("review_projections")),
            "internal_review_refs": _split_csv_list(packet.get("internal_review_refs")),
            "missing_review_outputs": missing_outputs,
            "outcome_metric_available": flow.get("outcome_metric_available"),
            "mean_prediction_score": flow.get("mean_prediction_score"),
            "score_label_spearman": flow.get("score_label_spearman"),
            "score_return_spearman": flow.get("score_return_spearman"),
            "mean_realized_return": flow.get("mean_realized_return"),
            "hit_rate": flow.get("hit_rate"),
            "tail_loss_count": flow.get("tail_loss_count"),
            "stage_verdict": _first_present(flow.get("stage_verdict"), packet.get("survival_verdict")),
            "verdict_basis": _first_present(flow.get("verdict_basis"), packet.get("survival_verdict_basis")),
            "metric_effectiveness_status": packet.get("metric_effectiveness_status"),
            "metric_effectiveness_flags": _split_csv_list(packet.get("metric_effectiveness_flags")),
            "can_assign_operation_fault": packet.get("can_assign_operation_fault"),
            "interpretation_status": packet.get("interpretation_status"),
            "metric_row_count": len(metrics),
            "metric_rows_returned": len(metric_rows_returned),
            "action_row_count": len(actions),
            "action_rows_returned": len(action_rows_returned),
            "availability_status_counts": availability_counts,
            "data_gap_metric_count": data_gap_metric_count,
            "computed_metric_count": computed_metric_count,
            "not_applicable_metric_count": not_applicable_metric_count,
            "metric_family_counts": metric_family_counts,
            "analysis_method_counts": analysis_method_counts,
            "required_evidence_status_counts": required_evidence_status_counts,
            "mean_metric_value": _operation_numeric_mean(metrics, "value"),
            "mean_opportunity_cost_to_best": _operation_numeric_mean(metrics, "opportunity_cost_to_best_mean"),
            "mean_selected_forward_return": _operation_numeric_mean(metrics, "selected_forward_return_mean"),
            "mean_top_quartile_hit_rate": _operation_numeric_mean(metrics, "top_quartile_hit_rate"),
            "evidence_status": "published" if flow or packet or metrics else "not_published",
            "source_gap_codes": component_gaps,
        }

    if action_rows and (flow_rows or packet_rows or metric_rows):
        status = "ready"
    elif flow_rows or packet_rows or metric_rows:
        status = "missing_primary_operation_action_rows"
    else:
        status = "insufficient_source_evidence"

    return {
        "contract_version": 1,
        "status": status,
        "included_components": [
            {"component_id": component_id, "component_label": component_label}
            for component_id, component_label in REPLAY_OPERATION_COMPONENTS
        ],
        "component_summary": component_summary,
        "macro_comparison": list(component_summary.values()),
        "component_metric_rows": component_metric_rows,
        "component_action_rows": component_action_rows,
        "detail_row_count": sum(len(rows) for rows in actions_by_component.values()),
        "detail_rows_returned": len(component_action_rows),
        "detail_rows_sampled": sum(len(rows) for rows in actions_by_component.values()) > len(component_action_rows),
        "metric_detail_row_count": sum(len(rows) for rows in metrics_by_component.values()),
        "metric_detail_rows_returned": len(component_metric_rows),
        "source_gap_codes": sorted(set(source_gap_codes)),
        "classification_policy": {
            "zero_values": "Published numeric zero means the operation component measured a true zero, not missing evidence.",
            "shared_envelope": "C01-C07 action rows share identity, action, input/output, evidence refs, and status fields; operation_action and analysis_method define component-specific interpretation.",
            "c03_lifecycle": "C03 must publish portfolio lifecycle state evidence or a lifecycle evidence gap; it is not excluded as a separate replay mode.",
            "missing_values": "Blank operation metric values remain null only when the upstream artifact does not publish that specific metric.",
        },
    }


def _review_layer_decision_row(row: Mapping[str, Any], layer_id: str) -> dict[str, Any]:
    correctness = _correctness_class(row)
    return {
        "review_id": row.get("review_id"),
        "decision_time": row.get("decision_time"),
        "target_symbol": row.get("target_symbol"),
        "replay_month": row.get("replay_month"),
        "source_decision_id": row.get("source_decision_id"),
        "source_decision_index": row.get("source_decision_index"),
        "layer_id": layer_id,
        "layer_label": REPLAY_DECISION_LAYER_LABELS[layer_id],
        "candidate_set_scope": row.get("candidate_set_scope"),
        "path_scope": row.get("path_scope"),
        "effective_decision": row.get("chosen_action"),
        "chosen_action": row.get("chosen_action"),
        "available_action": row.get("available_action"),
        "best_available_action_by_future_outcome": row.get("best_available_action_by_future_outcome"),
        "chosen_action_return": row.get("chosen_action_return"),
        "best_available_action_return": row.get("best_available_action_return"),
        "correctness_class": correctness,
        "acceptability_class": _acceptability_class(correctness),
        "regret_to_best_available": _review_regret_value(row),
        "impact_normalized_severity_score": _review_impact_value(row),
        "cause_family": row.get("cause_family"),
        "failure_type": row.get("failure_type"),
        "first_gap_component": row.get("first_gap_component"),
        "first_gap_mechanism": row.get("first_gap_mechanism"),
        "outcome_label": row.get("outcome_label"),
        "classification_basis": "derived_from_post_replay_best_available_action_label",
        "hindsight_caution": "Future returns are labels for review; they are not decision-time inputs.",
    }


def _published_layer_decision_row(row: Mapping[str, Any]) -> dict[str, Any]:
    layer_id = str(row.get("layer_id") or "")
    correctness = _correctness_class(row)
    fields = (
        "review_id",
        "decision_time",
        "target_symbol",
        "target_ref",
        "replay_month",
        "source_decision_id",
        "source_decision_index",
        "layer_id",
        "layer_label",
        "layer_order",
        "metric_family",
        "analysis_method",
        "decision_time_input_fields",
        "post_replay_label_fields",
        "label_role",
        "candidate_set_scope",
        "path_scope",
        "path_conditioning_policy",
        "effective_decision",
        "effective_decision_status",
        "selected_output_ref",
        "chosen_action",
        "available_action",
        "best_available_action_by_future_outcome",
        "chosen_action_return",
        "best_available_action_return",
        "correctness_class",
        "acceptability_class",
        "scoring_status",
        "classification_basis",
        "regret_to_best_available",
        "impact_normalized_severity_score",
        "cause_family",
        "failure_type",
        "first_gap_component",
        "first_gap_mechanism",
        "outcome_label",
        "realized_return",
        "baseline_return",
        "directional_underlying_return",
        "model_ref",
        "layer_diagnostics",
        "trace_evidence",
        "evidence_refs",
        "hindsight_caution",
    )
    projected = {field: row.get(field) for field in fields if field in row}
    projected.setdefault("layer_label", REPLAY_DECISION_LAYER_LABELS.get(layer_id, layer_id))
    projected["correctness_class"] = correctness
    projected["acceptability_class"] = str(row.get("acceptability_class") or _acceptability_class(correctness))
    projected["regret_to_best_available"] = _review_regret_value(projected)
    projected["impact_normalized_severity_score"] = _review_impact_value(projected)
    projected.setdefault("source", "post_replay_layer_decision_review_row")
    return projected


def _effective_layer_trace_row(
    row: Mapping[str, Any],
    *,
    source_decision_index: int,
    layer_id: str,
    review_overlay: Mapping[str, Any] | None,
) -> dict[str, Any]:
    diagnostics = _layer_diagnostics(row, layer_id)
    source_id = _source_decision_id(row, fallback_index=source_decision_index)
    if review_overlay is not None:
        overlay = _review_layer_decision_row(review_overlay, layer_id)
        overlay["source"] = "post_replay_review_row"
        overlay["source_decision_index"] = overlay.get("source_decision_index") or source_decision_index
        return overlay

    scored_overlay = _scored_layer_overlay(row, layer_id)
    correctness = str(scored_overlay.get("correctness_class") or "indeterminate")
    candidate_scope_by_layer = {
        "model_01_background_context": "background_context_state",
        "model_02_target_state": "selected_target_candidate_handoff",
        "model_03_event_state": "selected_path_event_state",
        "model_04_unified_decision": "selected_target_underlying_decision",
        "model_05_option_expression": row.get("candidate_set_scope") or "selected_target_selected_option_contract_path",
    }
    return {
        "review_id": f"{source_id}:{layer_id}",
        "decision_time": _decision_time(row),
        "target_symbol": _target_symbol(row),
        "replay_month": row.get("replay_month"),
        "source_decision_id": source_id,
        "source_decision_index": source_decision_index,
        "layer_id": layer_id,
        "layer_label": REPLAY_DECISION_LAYER_LABELS[layer_id],
        "candidate_set_scope": candidate_scope_by_layer[layer_id],
        "path_scope": row.get("path_scope"),
        "effective_decision": _effective_layer_decision(row, layer_id, diagnostics),
        "chosen_action": scored_overlay.get("chosen_action"),
        "available_action": scored_overlay.get("available_action"),
        "best_available_action_by_future_outcome": scored_overlay.get("best_available_action_by_future_outcome"),
        "chosen_action_return": scored_overlay.get("chosen_action_return"),
        "best_available_action_return": scored_overlay.get("best_available_action_return"),
        "correctness_class": correctness,
        "acceptability_class": _acceptability_class(correctness),
        "regret_to_best_available": _review_regret_value(scored_overlay),
        "impact_normalized_severity_score": _review_impact_value(scored_overlay),
        "cause_family": "not_attributed" if scored_overlay else "not_scored",
        "failure_type": "none" if correctness == "correct" else "not_scored",
        "first_gap_component": "no_gap" if correctness == "correct" else None,
        "first_gap_mechanism": "no_gap" if correctness == "correct" else None,
        "outcome_label": row.get("outcome_label"),
        "model_ref": _layer_ref(row, layer_id) or diagnostics.get("model_ref"),
        "layer_diagnostics": dict(diagnostics),
        "source": "replay_decision_row",
        "scoring_status": "scored" if scored_overlay else UNSCORED_LAYER_TRACE_STATUS,
        "classification_basis": scored_overlay.get("classification_basis", "effective trace only; layer-specific correctness label is not published"),
        "hindsight_caution": "Future returns are labels for review; they are not decision-time inputs.",
    }


def _layer_quality_summary(
    *,
    layer_id: str,
    attributed_rows: list[dict[str, Any]],
    performance_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    layer_differentiation = (
        performance_summary.get("layer_differentiation")
        if isinstance(performance_summary, Mapping)
        else None
    )
    coverage = (
        layer_differentiation.get(layer_id)
        if isinstance(layer_differentiation, Mapping) and isinstance(layer_differentiation.get(layer_id), Mapping)
        else {}
    )
    coverage_row_count = coverage.get("row_count") if isinstance(coverage, Mapping) else None
    correct_count = sum(1 for row in attributed_rows if _correctness_class(row) == "correct")
    incorrect_count = sum(1 for row in attributed_rows if _correctness_class(row) == "incorrect")
    indeterminate_count = sum(1 for row in attributed_rows if _correctness_class(row) == "indeterminate")
    scored_decision_count = correct_count + incorrect_count
    unscored_decision_count = max(0, len(attributed_rows) - scored_decision_count)
    acceptable_count = correct_count
    unacceptable_count = incorrect_count
    harmful_error_count = sum(1 for row in attributed_rows if _is_harmful_error(row, _correctness_class(row)))
    missed_good_count = sum(1 for row in attributed_rows if _is_missed_good(row, _correctness_class(row)))
    effective_decision_count = len(attributed_rows)
    regret_value_count = sum(1 for row in attributed_rows if _review_regret_value(row) is not None)
    impact_value_count = sum(1 for row in attributed_rows if _review_impact_value(row) is not None)
    missing_regret_value_count = max(0, effective_decision_count - regret_value_count)
    missing_impact_value_count = max(0, effective_decision_count - impact_value_count)
    source_gap_codes: list[str] = []
    if not effective_decision_count:
        source_gap_codes.append("missing_effective_layer_decision_rows")
    elif unscored_decision_count:
        source_gap_codes.append("unscored_effective_layer_decision_rows")
    if missing_regret_value_count:
        source_gap_codes.append("missing_layer_regret_values")
    if missing_impact_value_count:
        source_gap_codes.append("missing_layer_impact_values")
    if coverage_row_count is None:
        source_gap_codes.append("missing_layer_coverage_rows")
    evidence_status = (
        "published"
        if scored_decision_count
        else UNSCORED_LAYER_TRACE_STATUS
        if effective_decision_count
        else "coverage_only_missing_decision_quality"
        if coverage_row_count
        else "not_published"
    )
    first_row = attributed_rows[0] if attributed_rows else {}
    return {
        "layer_id": layer_id,
        "layer_label": REPLAY_DECISION_LAYER_LABELS[layer_id],
        "metric_family": first_row.get("metric_family"),
        "analysis_method": first_row.get("analysis_method"),
        "label_role": first_row.get("label_role"),
        "coverage_row_count": coverage_row_count,
        "effective_decision_count": effective_decision_count,
        "scored_decision_count": scored_decision_count,
        "unscored_decision_count": unscored_decision_count,
        "correct_count": correct_count,
        "acceptable_count": acceptable_count,
        "incorrect_count": incorrect_count,
        "unacceptable_count": unacceptable_count,
        "indeterminate_count": indeterminate_count,
        "harmful_error_count": harmful_error_count,
        "missed_good_count": missed_good_count,
        "regret_value_count": regret_value_count,
        "impact_value_count": impact_value_count,
        "missing_regret_value_count": missing_regret_value_count,
        "missing_impact_value_count": missing_impact_value_count,
        "correct_rate": _rate(correct_count, scored_decision_count),
        "acceptable_rate": _rate(acceptable_count, scored_decision_count),
        "incorrect_rate": _rate(incorrect_count, scored_decision_count),
        "harmful_error_rate": _rate(harmful_error_count, scored_decision_count),
        "missed_good_rate": _rate(missed_good_count, scored_decision_count),
        "mean_regret_to_best_available": _numeric_mean_by(attributed_rows, _review_regret_value),
        "mean_impact_normalized_severity_score": _numeric_mean_by(attributed_rows, _review_impact_value),
        "quality_score": _rate(acceptable_count, scored_decision_count),
        "evidence_status": evidence_status,
        "source_gap_codes": source_gap_codes,
    }


def _replay_decisions_m01_m05_summary(
    *,
    rows_path: Path | None,
    layer_rows_path: Path | None,
    decision_rows_path: Path | None,
    performance_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    review_rows = list(_iter_jsonl(rows_path)) if rows_path else []
    published_layer_rows = list(_iter_jsonl(layer_rows_path)) if layer_rows_path else []
    decision_rows = list(_iter_jsonl(decision_rows_path)) if decision_rows_path else []
    included_rows: list[dict[str, Any]] = []
    excluded_row_count = 0
    unattributed_row_count = 0
    for row in review_rows:
        layer_id = _row_layer_id(row)
        if layer_id in EXCLUDED_REPLAY_DECISION_LAYER_IDS:
            excluded_row_count += 1
            continue
        if layer_id is None:
            unattributed_row_count += 1
            continue
        if layer_id in REPLAY_DECISION_LAYER_IDS:
            included_rows.append({**row, "layer_id": layer_id})
    if published_layer_rows:
        effective_rows = []
        for row in published_layer_rows:
            layer_id = _normalized_layer_id(row.get("layer_id"))
            if layer_id in EXCLUDED_REPLAY_DECISION_LAYER_IDS:
                excluded_row_count += 1
                continue
            if layer_id in REPLAY_DECISION_LAYER_IDS:
                effective_rows.append(_published_layer_decision_row({**row, "layer_id": layer_id}))
            else:
                unattributed_row_count += 1
    elif decision_rows:
        overlays = _review_rows_by_source_and_layer(included_rows)
        effective_rows = [
            _effective_layer_trace_row(
                row,
                source_decision_index=index,
                layer_id=layer_id,
                review_overlay=overlays.get((_source_decision_id(row, fallback_index=index), layer_id)),
            )
            for index, row in enumerate(decision_rows, start=1)
            for layer_id in REPLAY_DECISION_LAYER_IDS
        ]
    else:
        effective_rows = [
            _review_layer_decision_row(row, str(row["layer_id"]))
            for row in included_rows
        ]

    rows_by_layer = {
        layer_id: [row for row in effective_rows if row["layer_id"] == layer_id]
        for layer_id in REPLAY_DECISION_LAYER_IDS
    }
    layer_quality_summary = {
        layer_id: _layer_quality_summary(
            layer_id=layer_id,
            attributed_rows=rows_by_layer[layer_id],
            performance_summary=performance_summary,
        )
        for layer_id in REPLAY_DECISION_LAYER_IDS
    }
    source_gap_codes = sorted(
        {
            gap
            for summary in layer_quality_summary.values()
            for gap in summary.get("source_gap_codes", [])
        }
    )
    if unattributed_row_count:
        source_gap_codes.append("unattributed_review_rows")
    sampled_rows = effective_rows[:MAX_LAYER_DECISION_ROWS]
    return {
        "contract_version": 1,
        "status": "ready" if effective_rows else "insufficient_source_evidence",
        "included_layers": [
            {"layer_id": layer_id, "layer_label": REPLAY_DECISION_LAYER_LABELS[layer_id]}
            for layer_id in REPLAY_DECISION_LAYER_IDS
        ],
        "excluded_layers": [
            {
                "layer_id": layer_id,
                "layer_label": REPLAY_DECISION_LAYER_LABELS[layer_id],
                "reason": "post_replay_residual_event_governance_not_in_decision_scope",
            }
            for layer_id in EXCLUDED_REPLAY_DECISION_LAYER_IDS
        ],
        "layer_quality_summary": layer_quality_summary,
        "macro_comparison": list(layer_quality_summary.values()),
        "layer_decision_rows": sampled_rows,
        "detail_row_count": len(effective_rows),
        "detail_rows_returned": len(sampled_rows),
        "detail_rows_sampled": len(effective_rows) > len(sampled_rows),
        "excluded_row_count": excluded_row_count,
        "unattributed_row_count": unattributed_row_count,
        "source_gap_codes": source_gap_codes,
        "classification_policy": {
            "correctness_class": "Derived from published M01-M05 layer review rows when available; legacy fallback uses replay decision traces and scored M04/M05 labels only.",
            "acceptability_class": "Correct rows are acceptable; incorrect rows are unacceptable until a narrower acceptance threshold is published.",
            "unscored_effective_trace": "Only legacy review runs without layer_review_rows_ref use unscored effective traces.",
            "hindsight_caution": "Future returns are labels for review; they must not be displayed as decision-time inputs.",
        },
    }


def _parameter_summary(report: Mapping[str, Any] | None) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report, Mapping) else None
    if not isinstance(summary, Mapping):
        return {}
    return {
        "parameter_count": summary.get("parameter_count"),
        "classification_counts": summary.get("classification_counts") or {},
        "directionally_useful_parameters": summary.get("directionally_useful_parameters") or [],
        "suspect_requires_redesign_parameters": summary.get("suspect_requires_redesign_parameters") or [],
        "interpretation_limits": summary.get("interpretation_limits") or [],
        "fixed_input_only": summary.get("fixed_input_only"),
        "threshold_selection_performed": summary.get("threshold_selection_performed"),
    }


def _review_run_summary(run_dir: Path) -> dict[str, Any] | None:
    receipt = _read_json_object(run_dir / "post_replay_review_receipt.json")
    if not receipt:
        return None
    scope = _current_replay_scope(receipt)
    if not scope["include"]:
        return None
    performance_summary = _read_json_object(run_dir / "replay_review_performance_summary.json")
    parameter_report = _read_json_object(run_dir / "layer_attribution" / "parameter_replay_review_report.json")
    rows_path = run_dir / "replay_review_rows.jsonl"
    if not rows_path.exists():
        rows_ref = receipt.get("review_rows_ref") or receipt.get("replay_review_rows_ref")
        rows_path = Path(str(rows_ref)) if rows_ref else rows_path
    layer_rows_path = run_dir / "replay_layer_decision_review_rows.jsonl"
    if not layer_rows_path.exists():
        layer_rows_ref = receipt.get("layer_review_rows_ref") or receipt.get("replay_layer_decision_review_rows_ref")
        layer_rows_path = Path(str(layer_rows_ref)) if layer_rows_ref else layer_rows_path
    decision_rows_path = Path(str(receipt.get("decision_rows_ref") or ""))
    return {
        "review_run_id": run_dir.name,
        "candidate_model_ref": receipt.get("candidate_model_ref"),
        "candidate_fold_id": receipt.get("candidate_fold_id"),
        "candidate_training_target": receipt.get("candidate_training_target"),
        "target_symbol": receipt.get("target_symbol") or receipt.get("candidate_training_target"),
        "replay_execution_run_id": receipt.get("replay_execution_run_id"),
        "created_at_utc": receipt.get("created_at_utc"),
        "completed_at_utc": receipt.get("completed_at_utc"),
        "processed_review_count": receipt.get("processed_review_count"),
        "expected_review_count": receipt.get("expected_review_count"),
        "event_candidate_count": receipt.get("event_candidate_count"),
        "performance": _compact_performance_summary(performance_summary),
        "decision_review": _review_rows_summary(rows_path if rows_path.exists() else None),
        "standard_review_diagnostics": _standard_review_diagnostics(run_dir / "layer_attribution"),
        "replay_decisions_m01_m05": _replay_decisions_m01_m05_summary(
            rows_path=rows_path if rows_path.exists() else None,
            layer_rows_path=layer_rows_path if layer_rows_path.exists() else None,
            decision_rows_path=decision_rows_path if decision_rows_path.exists() else None,
            performance_summary=performance_summary,
        ),
        "replay_operations_c01_c07": _replay_operations_c01_c07_summary(run_dir / "layer_attribution"),
        "parameter_review": _parameter_summary(parameter_report),
        "source_refs": {
            "receipt_ref": str(run_dir / "post_replay_review_receipt.json"),
            "performance_summary_ref": str(run_dir / "replay_review_performance_summary.json"),
            "review_rows_ref": str(rows_path) if rows_path.exists() else None,
            "layer_review_rows_ref": str(layer_rows_path) if layer_rows_path.exists() else None,
            "decision_rows_ref": str(decision_rows_path) if decision_rows_path.exists() else None,
            "parameter_report_ref": str(run_dir / "layer_attribution" / "parameter_replay_review_report.json")
            if (run_dir / "layer_attribution" / "parameter_replay_review_report.json").exists()
            else None,
            "operation_component_flow_ref": str(run_dir / "layer_attribution" / "operation_component_flow.csv")
            if (run_dir / "layer_attribution" / "operation_component_flow.csv").exists()
            else None,
            "operation_component_review_packet_ref": str(
                run_dir / "layer_attribution" / "operation_component_review_packet.csv"
            )
            if (run_dir / "layer_attribution" / "operation_component_review_packet.csv").exists()
            else None,
            "operation_component_metrics_ref": str(run_dir / "layer_attribution" / "operation_component_metrics.csv")
            if (run_dir / "layer_attribution" / "operation_component_metrics.csv").exists()
            else None,
            "operation_component_action_rows_ref": str(
                run_dir / "layer_attribution" / "operation_component_action_rows.csv"
            )
            if (run_dir / "layer_attribution" / "operation_component_action_rows.csv").exists()
            else None,
        },
    }


def _run_decision_trace_signature(run: Mapping[str, Any]) -> dict[str, Any]:
    operations = run.get("replay_operations_c01_c07")
    action_rows = (
        operations.get("component_action_rows")
        if isinstance(operations, Mapping) and isinstance(operations.get("component_action_rows"), list)
        else []
    )
    normalized_rows = []
    for row in action_rows:
        if not isinstance(row, Mapping):
            continue
        normalized_rows.append(
            {
                "component_id": row.get("component_id"),
                "decision_time": row.get("decision_time"),
                "target_symbol": row.get("target_symbol"),
                "operation_action": row.get("operation_action"),
                "operation_status": row.get("operation_status"),
                "input_summary": row.get("input_summary"),
                "output_summary": row.get("output_summary"),
                "block_reason": row.get("block_reason"),
                "realized_return": row.get("realized_return"),
                "regret_to_best_available": row.get("regret_to_best_available"),
            }
        )
    return {
        "signature": _json_digest(normalized_rows),
        "row_count": len(normalized_rows),
        "source": "replay_operations_component_action_rows",
    }


def _cross_model_group_duplicate_trace_diagnostics(review_runs: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in review_runs:
        signature = _run_decision_trace_signature(run)
        if not signature["row_count"]:
            continue
        groups.setdefault(str(signature["signature"]), []).append(
            {
                "candidate_fold_id": run.get("candidate_fold_id"),
                "target_symbol": run.get("target_symbol"),
                "review_run_id": run.get("review_run_id"),
                "row_count": signature["row_count"],
            }
        )
    duplicate_groups = [
        {
            "duplicate_trace_group_id": f"duplicate_trace_{index:03d}",
            "decision_trace_signature": signature,
            "member_count": len(members),
            "members": members,
            "risk": "non_independent_replay_decision_evidence",
        }
        for index, (signature, members) in enumerate(sorted(groups.items()), start=1)
        if len(members) > 1
    ]
    return {
        "contract_version": 1,
        "status": "ready" if groups else "insufficient_source_evidence",
        "signature_count": len(groups),
        "duplicate_trace_group_count": len(duplicate_groups),
        "duplicate_trace_member_count": sum(group["member_count"] for group in duplicate_groups),
        "duplicate_trace_groups": duplicate_groups,
        "classification_policy": {
            "meaning": "Duplicate trace groups flag model groups whose published replay operation action rows are indistinguishable after run identifiers are removed.",
            "review_use": "Treat duplicate groups as independence risk; do not count them as separate evidence without inspecting the upstream model and selection route.",
        },
    }


def build_model_group_replay_review_summary(
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the dashboard replay review summary from existing artifacts."""

    generated_at_utc = generated_at_utc or now_utc()
    replay_root = storage_root / DEFAULT_REPLAY_ROOT
    review_root = replay_root / "post_replay_review_runs"
    review_run_candidates = [
        summary
        for run_dir in _latest_dirs(review_root, "post_replay_review_*", MAX_REVIEW_RUNS)
        if (summary := _review_run_summary(run_dir)) is not None
    ]
    review_runs, superseded_review_run_count = _latest_review_run_per_fold(review_run_candidates)
    cross_model_group_diagnostics = _cross_model_group_duplicate_trace_diagnostics(review_runs)
    total_review_rows = sum(int(run.get("decision_review", {}).get("row_count") or 0) for run in review_runs)
    status = "ready" if review_runs else "not_reported"
    return {
        "contract_type": MODEL_GROUP_REPLAY_REVIEW_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": status,
        "severity": "info" if status == "ready" else "low",
        "summary": (
            f"Replay review summary has {len(review_runs)} review runs and {total_review_rows} review rows."
        )
        if status == "ready"
        else "No post-replay review artifacts are published yet.",
        "chart_payload": {
            "review_runs": review_runs,
            "cross_model_group_diagnostics": cross_model_group_diagnostics,
            "contract_matrix": {
                "comparison_dimension": "model_group_between_run_compare",
                "individual_dimension": "single_model_group_review_run",
                "detail_dimension": "focus_detail_by_source_ref",
                "hindsight_caution": "Future returns are labels for review; they must not be displayed as decision-time inputs.",
            },
        },
        "profile_refs": [{"registry_ref": "MODEL_GROUP_REPLAY_REVIEW_SUMMARY", "field": "contract_type"}],
        "issue_refs": [],
        "diagnostic_refs": [],
        "lineage_refs": [
            {
                "artifact_root": str(review_root),
                "candidate_run_count": len(review_run_candidates),
                "included_run_count": len(review_runs),
                "superseded_review_run_count": superseded_review_run_count,
            },
        ],
        "freshness": {
            "class": "derived_replay_review_summary",
            "status": "fresh" if status == "ready" else "no_source_summary",
            "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS,
        },
        "schema_ref": MODEL_GROUP_REPLAY_REVIEW_SCHEMA_REF,
    }


def refresh_model_group_replay_review_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    payload = build_model_group_replay_review_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(
        payload,
        storage_root=storage_root,
        expected_contract_type=MODEL_GROUP_REPLAY_REVIEW_CONTRACT,
    )
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": MODEL_GROUP_REPLAY_REVIEW_CONTRACT,
        "materialized": dict(materialized.index_row),
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


__all__ = [
    "MODEL_GROUP_REPLAY_REVIEW_CONTRACT",
    "build_model_group_replay_review_summary",
    "refresh_model_group_replay_review_summary_read_model",
]
