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

MODEL_READINESS_CONTRACT = "model_readiness_summary"
MODEL_PROMOTION_POSTURE_CONTRACT = "model_promotion_posture_summary"
MODEL_READINESS_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_READINESS_CONTRACT}.schema.json"
MODEL_PROMOTION_POSTURE_SCHEMA_REF = f"storage/06_dashboard_cache/schemas/{MODEL_PROMOTION_POSTURE_CONTRACT}.schema.json"

HISTORICAL_TASK_PROGRESS_CONTRACT = "historical_task_progress_summary"
EXECUTION_RUNTIME_STATUS_CONTRACT = "execution_realtime_trading_runtime_status"
DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_STALE_AFTER_SECONDS = 900
CURRENT_MODEL_WORKER_FOLD_RE = re.compile(r"^fold_[a-z0-9]+_20\d{2}$")

MODEL_LAYERS = (
    (1, "model_01_background_context", "Background Context"),
    (2, "model_02_target_state", "Target State"),
    (3, "model_03_event_state", "Event State"),
    (4, "model_04_unified_decision", "Unified Decision"),
    (5, "model_05_option_expression", "Option Expression"),
)


def _current_model_worker_fold_id(value: object) -> str:
    fold_id = str(value or "").strip().lower()
    return fold_id if CURRENT_MODEL_WORKER_FOLD_RE.fullmatch(fold_id) else ""


def _read_latest(storage_root: Path, contract_type: str) -> dict[str, Any] | None:
    path = storage_root / "06_dashboard_cache" / "read_models" / f"{contract_type}.json"
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
    return model_id in normalized or f"m{layer:02d}" in normalized or f"model_{layer:02d}" in normalized


def _global_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    matches = [task for task in tasks if task.get("task_id") == task_id]
    if not matches:
        return None
    return max(matches, key=lambda task: str(task.get("status_updated_at_utc") or task.get("updated_at_utc") or task.get("created_at_utc") or ""))


def _model_group_evidence_publishable(tasks: list[dict[str, Any]], *, active_ref: str | None) -> bool:
    if active_ref:
        return True
    publishable_ids = {
        "model_group.evaluation",
        "model_group.promotion",
        "model_group.maintenance",
    }
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        task_state = str(task.get("task_state") or "").lower()
        if task_id in publishable_ids and task_state != "future":
            return True
    return False


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


def _first_nonempty_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _utc_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _file_timestamp(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _artifact_timestamp(path: Path, payload: Mapping[str, Any] | None = None) -> float | None:
    if payload is None:
        payload = _load_json_object(path) or {}
    for key in (
        "created_at_utc",
        "generated_at_utc",
        "completed_at_utc",
        "ended_at_utc",
        "updated_at_utc",
        "timestamp_utc",
    ):
        timestamp = _utc_timestamp(payload.get(key))
        if timestamp is not None:
            return timestamp
    return _file_timestamp(path)


def _model_group_scope_key(target: str, start_month: str, end_month: str) -> str:
    normalized_target = target.strip().upper().replace("_", ".")
    return f"{normalized_target}:{start_month}_{end_month}" if normalized_target and start_month and end_month else ""


def _model_group_scope_key_from_candidate_ref(candidate_model_ref: str) -> str:
    match = re.search(
        r"/model_group/(?P<target>[A-Za-z0-9_]+)/(?P<start>20\d{2}-\d{2})_(?P<end>20\d{2}-\d{2})$",
        candidate_model_ref,
    )
    if not match:
        return ""
    return _model_group_scope_key(match.group("target"), match.group("start"), match.group("end"))


def _model_group_scope_key_from_reset_receipt(receipt: Mapping[str, Any]) -> str:
    state_path = str(receipt.get("state_path") or "")
    match = re.search(
        r"model_training_fold_state_(?P<target>[A-Za-z0-9_]+)_(?P<start>20\d{2}-\d{2})_(?P<end>20\d{2}-\d{2})\.json$",
        state_path,
    )
    if match:
        return _model_group_scope_key(match.group("target"), match.group("start"), match.group("end"))
    rerun_id = str(receipt.get("rerun_id") or "")
    rerun_match = re.search(
        r"model_group_rerun_(?P<start>20\d{2}-\d{2})_(?P<end>20\d{2}-\d{2})",
        rerun_id,
    )
    target = str(receipt.get("target_symbol") or receipt.get("candidate_training_target") or "").strip()
    if rerun_match and target:
        return _model_group_scope_key(target, rerun_match.group("start"), rerun_match.group("end"))
    return ""


def _model_group_rerun_reset_floors(storage_root: Path) -> dict[str, dict[str, Any]]:
    reset_root = storage_root / "02_control_plane" / "runtime" / "model_group_rerun_resets"
    if not reset_root.exists():
        return {}
    floors: dict[str, dict[str, Any]] = {}
    for receipt_path in sorted(reset_root.glob("*/**/*.reset_receipt.json")):
        receipt = _load_json_object(receipt_path)
        if receipt is None or receipt.get("contract_type") != "manager_model_group_rerun_reset_receipt":
            continue
        scope_key = _model_group_scope_key_from_reset_receipt(receipt)
        if not scope_key:
            continue
        timestamp = _artifact_timestamp(receipt_path, receipt)
        if timestamp is None:
            continue
        existing = floors.get(scope_key)
        if existing is None or timestamp >= float(existing["timestamp"]):
            floors[scope_key] = {
                "timestamp": timestamp,
                "reset_ref": str(receipt_path),
                "reset_created_at_utc": receipt.get("created_at_utc"),
                "cutpoint_stage_id": receipt.get("cutpoint_stage_id"),
                "rerun_id": receipt.get("rerun_id"),
            }
    return floors


def _model_group_evidence_timestamps(
    *,
    decision_path: Path,
    decision: Mapping[str, Any],
    review: Mapping[str, Any],
    receipt: Mapping[str, Any],
    settlement_path: Path,
    settlement: Mapping[str, Any] | None,
    replay_result_ref: str,
) -> list[float]:
    artifacts: list[tuple[Path, Mapping[str, Any] | None]] = [
        (decision_path, decision),
        (decision_path.parent / "promotion_evaluation_review.json", review),
        (decision_path.parent / "model_group_evaluation_receipt.json", receipt),
    ]
    if isinstance(settlement, Mapping):
        artifacts.append((settlement_path, settlement))
    if replay_result_ref:
        replay_path = Path(replay_result_ref)
        artifacts.append((replay_path, _load_json_object(replay_path)))
    timestamps: list[float] = []
    for path, payload in artifacts:
        timestamp = _artifact_timestamp(path, payload)
        if timestamp is not None:
            timestamps.append(timestamp)
    return timestamps


def _model_group_rerun_reset_exclusion_reason(
    *,
    reset_floors: Mapping[str, Mapping[str, Any]],
    candidate_model_ref: str,
    evidence_timestamps: list[float],
) -> dict[str, Any] | None:
    if not evidence_timestamps:
        return None
    scope_key = _model_group_scope_key_from_candidate_ref(candidate_model_ref)
    if not scope_key:
        return None
    reset = reset_floors.get(scope_key)
    if not reset:
        return None
    reset_timestamp = float(reset.get("timestamp") or 0.0)
    if min(evidence_timestamps) >= reset_timestamp:
        return None
    return {
        "reason_code": "superseded_by_model_group_rerun_reset",
        "reason": "promotion evidence chain includes artifacts that predate the latest model-group rerun reset for this fold",
        "reset_ref": str(reset.get("reset_ref") or ""),
        "reset_created_at_utc": reset.get("reset_created_at_utc"),
        "cutpoint_stage_id": reset.get("cutpoint_stage_id"),
        "rerun_id": reset.get("rerun_id"),
    }


def _explicit_model_training_targets(storage_root: Path) -> set[str]:
    queue_path = storage_root / "02_control_plane" / "runtime" / "model_training_target_queue.json"
    payload = _load_json_object(queue_path)
    if payload is None:
        return set()
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return set()
    explicit: set[str] = set()
    for row in targets:
        if not isinstance(row, Mapping):
            continue
        if row.get("enabled") is False:
            continue
        source = str(row.get("training_target_source") or "")
        symbol = str(row.get("symbol") or "").strip().upper()
        if source == "explicit_bootstrap_target" and symbol:
            explicit.add(symbol)
    return explicit


def _model_group_version_label(*, fold_id: str, candidate_model_ref: str, target_symbol: str, fallback: str) -> str:
    source = " ".join(item for item in [fold_id, candidate_model_ref, fallback] if item)
    target = target_symbol.strip().upper()
    target_year_match = re.search(r"fold[_-](?P<target>[a-z0-9]+)[_-](?P<year>20\d{2})", source, flags=re.IGNORECASE)
    if target_year_match:
        label_target = target or target_year_match.group("target").upper()
        return f"{label_target} {target_year_match.group('year')}"

    compact_match = re.search(
        r"(?P<year>20\d{2})[-_ ]?fold[-_ ]?(?P<fold>\d+)",
        source,
        flags=re.IGNORECASE,
    )
    if compact_match:
        label = f"{compact_match.group('year')} fold{int(compact_match.group('fold'))}"
        return f"{target} {label}" if target else f"Unscoped {label}"

    range_match = re.search(
        r"(?P<start_year>20\d{2})-(?P<start_month>\d{2})_(?P<end_year>20\d{2})-(?P<end_month>\d{2})",
        source,
    )
    if range_match:
        label = (
            f"{range_match.group('start_year')}-{range_match.group('start_month')}"
            f"..{range_match.group('end_year')}-{range_match.group('end_month')}"
        )
        return f"{target} {label}" if target else f"Unscoped {label}"

    return fallback


def _model_group_version_replay_contract_mismatch(
    decision: Mapping[str, Any],
    settlement: Mapping[str, Any] | None,
    *,
    candidate_model_ref: str,
    fold_id: str,
    target_symbol: str,
) -> str | None:
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
    candidate_handoff_status = str(replay_receipt.get("candidate_handoff_status") or "").strip().lower()
    if candidate_handoff_status not in {"available", "override"}:
        return "replay receipt lacks M02 target-candidate handoff evidence"
    if candidate_model_ref and candidate_ref != candidate_model_ref:
        return "replay receipt candidate_model_ref does not match promotion candidate_model_ref"
    replay_fold_id = str(replay_receipt.get("candidate_fold_id") or replay_receipt.get("fold_id") or "")
    if fold_id and replay_fold_id and replay_fold_id != fold_id:
        return "replay receipt fold_id does not match promotion fold_id"
    replay_target_symbol = str(replay_receipt.get("target_symbol") or "").strip().upper()
    if target_symbol and replay_target_symbol and replay_target_symbol != target_symbol:
        return "replay receipt target_symbol does not match promotion target_symbol"
    if target_symbol and not replay_target_symbol:
        return "replay receipt does not declare target_symbol"
    return None


def _model_group_version_exclusion_reasons(
    *,
    decision: Mapping[str, Any],
    settlement: Mapping[str, Any] | None,
    target_symbol: str,
    candidate_model_ref: str,
    fold_id: str,
    candidate_fold_id: str,
    candidate_training_target: str,
    replay_execution_run_id: str,
    explicit_training_targets: set[str],
) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    normalized_target = target_symbol.strip().upper()
    if not normalized_target:
        reasons.append({"reason_code": "missing_target_symbol", "reason": "promotion artifact does not declare a target_symbol"})
    elif explicit_training_targets and normalized_target not in explicit_training_targets:
        reasons.append(
            {
                "reason_code": "target_not_in_training_queue",
                "reason": f"promotion target {normalized_target} is not in the explicit model-worker training queue",
            }
        )
    if not candidate_fold_id.strip():
        reasons.append(
            {
                "reason_code": "missing_candidate_fold_id",
                "reason": "promotion artifact does not declare the candidate fold that owns this evaluation",
            }
        )
    elif not _current_model_worker_fold_id(candidate_fold_id):
        reasons.append(
            {
                "reason_code": "stale_replay_fold_id",
                "reason": "promotion artifact does not use current fold_<target>_<year> naming",
            }
        )
    if not candidate_training_target.strip():
        reasons.append(
            {
                "reason_code": "missing_candidate_training_target",
                "reason": "promotion artifact does not declare the explicit model-worker training target",
            }
        )
    if not replay_execution_run_id.strip():
        reasons.append(
            {
                "reason_code": "missing_replay_execution_run_id",
                "reason": "promotion artifact does not declare the replay execution run used for this evaluation",
            }
        )
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
    replay_contract_mismatch = _model_group_version_replay_contract_mismatch(
        decision,
        settlement,
        candidate_model_ref=candidate_model_ref,
        fold_id=fold_id,
        target_symbol=normalized_target,
    )
    if replay_contract_mismatch:
        reasons.append({"reason_code": "replay_candidate_handoff_missing", "reason": replay_contract_mismatch})
    alpha_artifact_reason = _model_group_version_alpha_artifact_reason(decision, settlement)
    if alpha_artifact_reason:
        reasons.append(alpha_artifact_reason)
    return reasons


def _model_group_version_alpha_artifact_reason(
    decision: Mapping[str, Any],
    settlement: Mapping[str, Any] | None,
) -> dict[str, str] | None:
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
    artifact_ref = str(replay_receipt.get("after_cost_alpha_model_ref") or "").strip()
    if not artifact_ref:
        return {
            "reason_code": "after_cost_alpha_model_missing",
            "reason": "replay receipt does not declare after_cost_alpha_model_ref",
        }
    artifact = _load_json_object(Path(artifact_ref))
    if artifact is None:
        return {
            "reason_code": "after_cost_alpha_model_missing",
            "reason": "after-cost alpha model artifact is missing or unreadable",
        }
    training_summary = artifact.get("training_summary")
    if not isinstance(training_summary, Mapping):
        training_summary = {}
    training_mode = str(training_summary.get("training_mode") or "").strip()
    sample_count = _int_value(training_summary.get("sample_count"))
    if training_mode == "policy_bundle_no_supervised_fit" or sample_count <= 0:
        return {
            "reason_code": "after_cost_alpha_model_not_trained",
            "reason": "after-cost alpha artifact is a no-supervised-fit policy bundle, not a trained fold-specific model",
        }
    return None


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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


def _metrics_with_replay_return_path_ohlc(
    metrics: Mapping[str, Any],
    *,
    settlement: Mapping[str, Any] | None,
    settlement_path: Path,
) -> dict[str, Any]:
    enriched = dict(metrics)
    temporal = enriched.get("temporal_stability_diagnostics")
    if not isinstance(temporal, Mapping):
        return enriched
    slices = temporal.get("slices")
    if not isinstance(slices, list):
        return enriched
    if all(isinstance(item, Mapping) and isinstance(item.get("net_return_path_ohlc"), Mapping) for item in slices):
        return enriched
    ohlc_by_month = _replay_return_path_ohlc_by_month(settlement=settlement, settlement_path=settlement_path)
    if not ohlc_by_month:
        return enriched
    enriched_slices: list[Any] = []
    for item in slices:
        if not isinstance(item, Mapping):
            enriched_slices.append(item)
            continue
        month = str(item.get("month") or "")
        row = dict(item)
        if not isinstance(row.get("net_return_path_ohlc"), Mapping) and month in ohlc_by_month:
            row["net_return_path_ohlc"] = ohlc_by_month[month]
        enriched_slices.append(row)
    enriched_temporal = dict(temporal)
    enriched_temporal["slices"] = enriched_slices
    enriched["temporal_stability_diagnostics"] = enriched_temporal
    return enriched


def _replay_return_path_ohlc_by_month(
    *,
    settlement: Mapping[str, Any] | None,
    settlement_path: Path,
) -> dict[str, dict[str, float]]:
    decision_rows_path = _decision_rows_path_for_settlement(settlement=settlement, settlement_path=settlement_path)
    if decision_rows_path is None:
        return {}
    by_month: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    try:
        with decision_rows_path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, Mapping):
                    continue
                if str(row.get("entry_threshold_calibration_role") or "test") == "validation":
                    continue
                month = _month_key(row.get("timestamp") or row.get("decision_timestamp"))
                if month:
                    by_month.setdefault(month, []).append((index, row))
    except OSError:
        return {}
    ohlc: dict[str, dict[str, float]] = {}
    for month, rows in by_month.items():
        ordered = sorted(rows, key=lambda item: (str(item[1].get("timestamp") or item[1].get("decision_timestamp") or ""), item[0]))
        returns = [_row_net_return(row) for _index, row in ordered]
        ohlc[month] = _return_path_ohlc(returns)
    return ohlc


def _decision_rows_path_for_settlement(
    *,
    settlement: Mapping[str, Any] | None,
    settlement_path: Path,
) -> Path | None:
    receipt_candidates: list[Path] = []
    direct_ref = str((settlement or {}).get("replay_result_ref") or "")
    if direct_ref:
        receipt_candidates.append(Path(direct_ref))
    dataset_root = settlement_path.parent.parent.parent
    replay_root = dataset_root / "replay_execution_runs"
    if replay_root.exists():
        receipt_candidates.extend(sorted(replay_root.glob("*/replay_execution_receipt.json")))
    expected_candidate_ref = str((settlement or {}).get("candidate_model_ref") or "")
    selected: tuple[float, Path] | None = None
    seen: set[Path] = set()
    for receipt_path in receipt_candidates:
        if receipt_path in seen:
            continue
        seen.add(receipt_path)
        receipt = _load_json_object(receipt_path)
        if receipt is None:
            continue
        if expected_candidate_ref and str(receipt.get("candidate_model_ref") or "") != expected_candidate_ref:
            continue
        decision_rows_ref = str(receipt.get("decision_rows_ref") or "")
        decision_rows_path = Path(decision_rows_ref) if decision_rows_ref else receipt_path.parent / "decision_rows.jsonl"
        if not decision_rows_path.exists():
            continue
        try:
            clock = receipt_path.stat().st_mtime
        except OSError:
            clock = 0.0
        if selected is None or clock >= selected[0]:
            selected = (clock, decision_rows_path)
    return selected[1] if selected else None


def _month_key(value: Any) -> str | None:
    match = re.search(r"(?P<month>\d{4}-\d{2})", str(value or ""))
    return match.group("month") if match else None


def _row_net_return(row: Mapping[str, Any]) -> float:
    gross = _float_value(row, "net_return", "realized_return", "candidate_return")
    cost = _float_value(row, "cost", "trading_cost", "cost_drag")
    return gross - cost


def _float_value(row: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _return_path_ohlc(returns: list[float]) -> dict[str, float]:
    current = 0.0
    high = 0.0
    low = 0.0
    for value in returns:
        current += float(value)
        high = max(high, current)
        low = min(low, current)
    return {
        "open": 1.0,
        "high": round(1.0 + high, 6),
        "low": round(1.0 + low, 6),
        "close": round(1.0 + current, 6),
    }


def _model_group_promotion_evidence(storage_root: Path, *, active_ref: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    review_root = storage_root / "05_replay_datasets" / "promotion_replay_candidate_policy" / "promotion_review_runs"
    if not review_root.exists():
        return [], []
    rows_by_version_key: dict[str, dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    explicit_training_targets = _explicit_model_training_targets(storage_root)
    reset_floors = _model_group_rerun_reset_floors(storage_root)
    for decision_path in sorted(review_root.glob("*/promotion_eligibility_decision.json")):
        decision = _load_json_object(decision_path)
        if decision is None:
            continue
        review = _load_json_object(decision_path.parent / "promotion_evaluation_review.json") or {}
        receipt = _load_json_object(decision_path.parent / "model_group_evaluation_receipt.json") or {}
        settlement_ref = _first_nonempty_string(
            decision.get("settlement_run_ref"),
            review.get("settlement_run_ref"),
            receipt.get("fold_settlement_run_ref"),
        )
        settlement_path = Path(settlement_ref) if settlement_ref else decision_path.parent / "fold_settlement_run.json"
        settlement = _load_json_object(settlement_path)
        raw_metrics = settlement.get("metrics") if isinstance(settlement, Mapping) and isinstance(settlement.get("metrics"), Mapping) else {}
        metrics = _metrics_with_replay_return_path_ohlc(raw_metrics, settlement=settlement, settlement_path=settlement_path)
        decision_status = str(decision.get("decision_status") or "not_reported")
        recommendation = str(decision.get("agent_review_recommendation") or review.get("recommendation") or "")
        candidate_model_ref = _first_nonempty_string(
            decision.get("candidate_model_ref"),
            review.get("candidate_model_ref"),
            receipt.get("candidate_model_ref"),
            receipt.get("model_group_ref"),
            settlement.get("candidate_model_ref") if isinstance(settlement, Mapping) else "",
            settlement.get("model_group_ref") if isinstance(settlement, Mapping) else "",
        )
        fold_id = _first_nonempty_string(
            decision.get("fold_id"),
            review.get("fold_id"),
            receipt.get("fold_id"),
            settlement.get("fold_id") if isinstance(settlement, Mapping) else "",
            receipt.get("candidate_fold_id"),
            settlement.get("candidate_fold_id") if isinstance(settlement, Mapping) else "",
        )
        candidate_fold_id = _first_nonempty_string(
            decision.get("candidate_fold_id"),
            review.get("candidate_fold_id"),
            receipt.get("candidate_fold_id"),
            settlement.get("candidate_fold_id") if isinstance(settlement, Mapping) else "",
            fold_id,
        )
        candidate_training_target = _first_nonempty_string(
            decision.get("candidate_training_target"),
            review.get("candidate_training_target"),
            receipt.get("candidate_training_target"),
            settlement.get("candidate_training_target") if isinstance(settlement, Mapping) else "",
        ).upper()
        replay_execution_run_id = _first_nonempty_string(
            decision.get("replay_execution_run_id"),
            review.get("replay_execution_run_id"),
            receipt.get("replay_execution_run_id"),
            settlement.get("replay_execution_run_id") if isinstance(settlement, Mapping) else "",
        )
        replay_result_ref = _first_nonempty_string(
            settlement.get("replay_result_ref") if isinstance(settlement, Mapping) else "",
            receipt.get("replay_execution_receipt_ref"),
            decision.get("replay_validation_ref"),
            decision.get("replay_result_ref"),
        )
        target_symbol = _first_nonempty_string(
            decision.get("target_symbol")
            or "",
            review.get("target_symbol") or "",
            receipt.get("target_symbol") or "",
            settlement.get("target_symbol") if isinstance(settlement, Mapping) else "",
            candidate_training_target,
            _target_symbol_from_candidate_ref(candidate_model_ref) or "",
        ).upper()
        exclusion_reasons: list[dict[str, Any]] = list(
            _model_group_version_exclusion_reasons(
                decision=decision,
                settlement=settlement,
                target_symbol=target_symbol,
                candidate_model_ref=candidate_model_ref,
                fold_id=fold_id,
                candidate_fold_id=candidate_fold_id,
                candidate_training_target=candidate_training_target,
                replay_execution_run_id=replay_execution_run_id,
                explicit_training_targets=explicit_training_targets,
            )
        )
        reset_reason = _model_group_rerun_reset_exclusion_reason(
            reset_floors=reset_floors,
            candidate_model_ref=candidate_model_ref,
            evidence_timestamps=_model_group_evidence_timestamps(
                decision_path=decision_path,
                decision=decision,
                review=review,
                receipt=receipt,
                settlement_path=settlement_path,
                settlement=settlement,
                replay_result_ref=replay_result_ref,
            ),
        )
        if reset_reason:
            exclusion_reasons.append(reset_reason)
        if exclusion_reasons:
            exclusions.append(
                {
                    "promotion_run_id": decision_path.parent.name,
                    "decision_ref": str(decision_path),
                    "settlement_ref": settlement_ref or None,
                    "fold_id": fold_id or None,
                    "candidate_fold_id": candidate_fold_id or None,
                    "candidate_training_target": candidate_training_target or None,
                    "replay_execution_run_id": replay_execution_run_id or None,
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
            "candidate_fold_id": candidate_fold_id,
            "candidate_training_target": candidate_training_target,
            "replay_execution_run_id": replay_execution_run_id or None,
            "replay_result_ref": replay_result_ref or None,
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
                "net_return_total": metrics.get("net_return_total"),
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
                "benchmark_symbol": metrics.get("benchmark_symbol"),
                "benchmark_return_total": metrics.get("benchmark_return_total"),
                "benchmark_month_count": metrics.get("benchmark_month_count"),
                "benchmark_beta": metrics.get("benchmark_beta"),
                "market_beta": metrics.get("market_beta"),
                "beta": metrics.get("beta"),
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
                "return_semantics_diagnostics": metrics.get("return_semantics_diagnostics"),
                "data_integrity_diagnostics": metrics.get("data_integrity_diagnostics"),
                "temporal_stability_diagnostics": metrics.get("temporal_stability_diagnostics"),
                "benchmark_diagnostics": metrics.get("benchmark_diagnostics"),
                "baseline_comparison_diagnostics": metrics.get("baseline_comparison_diagnostics"),
                "m05_expression_mechanics_diagnostics": metrics.get("m05_expression_mechanics_diagnostics"),
                "m04_m05_bridge_diagnostics": metrics.get("m04_m05_bridge_diagnostics"),
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
                "receipt_ref": str(decision_path.parent / "model_group_evaluation_receipt.json"),
                "settlement_ref": settlement_ref,
                "replay_result_ref": replay_result_ref,
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


def build_model_readiness_summary(
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
    if _model_group_evidence_publishable(tasks, active_ref=active_ref):
        group_versions, excluded_group_versions = _model_group_promotion_evidence(storage_root, active_ref=active_ref)
    else:
        group_versions, excluded_group_versions = [], []
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
                "layer_id": f"M{layer:02d}",
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
        "contract_type": MODEL_READINESS_CONTRACT,
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
        "profile_refs": [{"registry_ref": "MODEL_READINESS_SUMMARY", "field": "contract_type"}],
        "issue_refs": _exclusion_issue_refs(excluded_group_versions),
        "diagnostic_refs": [],
        "lineage_refs": _source_refs(historical, runtime),
        "freshness": _freshness([historical, runtime]),
        "schema_ref": MODEL_READINESS_SCHEMA_REF,
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
    if _model_group_evidence_publishable(tasks, active_ref=active_ref):
        group_versions, excluded_group_versions = _model_group_promotion_evidence(storage_root, active_ref=active_ref)
    else:
        group_versions, excluded_group_versions = [], []
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
        if version or is_active or blockers:
            rows.append(
                {
                    "layer": layer,
                    "layer_id": f"M{layer:02d}",
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


def refresh_model_readiness_summary_read_model(*, storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict[str, Any]:
    payload = build_model_readiness_summary(storage_root=storage_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=MODEL_READINESS_CONTRACT)
    return _refresh_receipt(MODEL_READINESS_CONTRACT, materialized.index_row)


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
    "MODEL_READINESS_CONTRACT",
    "MODEL_PROMOTION_POSTURE_CONTRACT",
    "build_model_readiness_summary",
    "build_model_promotion_posture_summary",
    "refresh_model_readiness_summary_read_model",
    "refresh_model_promotion_posture_summary_read_model",
]
