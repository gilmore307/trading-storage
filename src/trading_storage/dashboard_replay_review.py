"""Replay review dashboard read-model producer.

The producer projects already-materialized post-replay review artifacts into a
small owner-facing read model for the dashboard replay pages. It does not run
replay, review models, activate models, call providers, submit broker work, or
mutate account state.
"""

from __future__ import annotations

import json
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
CURRENT_MODEL_WORKER_FOLD_RE = re.compile(r"^fold_[a-z0-9]+_20\d{2}$")


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
    return {field: row.get(field) for field in fields if field in row}


def _review_rows_summary(rows_path: Path | None) -> dict[str, Any]:
    rows = list(_iter_jsonl(rows_path)) if rows_path else []
    return {
        "row_count": len(rows),
        "cause_family_counts": _count_by(rows, "cause_family"),
        "failure_type_counts": _count_by(rows, "failure_type"),
        "first_gap_component_counts": _count_by(rows, "first_gap_component"),
        "miss_attribution_layer_counts": _count_by(rows, "miss_attribution_layer"),
        "review_status_counts": _count_by(rows, "review_status"),
        "mean_regret_to_best_available": _numeric_mean(rows, "regret_to_best_available"),
        "mean_impact_normalized_severity_score": _numeric_mean(rows, "impact_normalized_severity_score"),
        "sample_rows": [_sample_review_row(row) for row in rows[:MAX_SAMPLE_ROWS]],
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
        "parameter_review": _parameter_summary(parameter_report),
        "source_refs": {
            "receipt_ref": str(run_dir / "post_replay_review_receipt.json"),
            "performance_summary_ref": str(run_dir / "replay_review_performance_summary.json"),
            "review_rows_ref": str(rows_path) if rows_path.exists() else None,
            "parameter_report_ref": str(run_dir / "layer_attribution" / "parameter_replay_review_report.json")
            if (run_dir / "layer_attribution" / "parameter_replay_review_report.json").exists()
            else None,
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
