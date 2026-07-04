"""Storage-owned lifecycle planner/executor for model-group rerun resets."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from trading_storage.io import append_text_locked, write_text_atomic

EXECUTOR_VERSION = "storage_rerun_reset_lifecycle_v0_1"
DEFAULT_RECEIPT_ROOT = Path("storage/90_lifecycle/receipts/rerun_reset_lifecycle")
DEFAULT_TOMBSTONE_ROOT = Path("storage/90_lifecycle/tombstones/rerun_reset_lifecycle")

RERUN_RESET_FILE_CLASSES: tuple[dict[str, str], ...] = (
    {
        "file_class": "workflow_state",
        "handling": "reset_state_not_delete",
        "description": "Manager-owned workflow state is invalidated in place by the manager reset receipt.",
    },
    {
        "file_class": "stage_receipts",
        "handling": "delete",
        "description": "Generated downstream stage receipts under the accepted cutpoint are removed before rerun.",
    },
    {
        "file_class": "stage_logs",
        "handling": "delete",
        "description": "stdout/stderr logs for invalidated downstream stages are runtime sidecars.",
    },
    {
        "file_class": "task_progress_sidecars",
        "handling": "delete",
        "description": "Generated task-progress files for invalidated downstream stages are runtime sidecars.",
    },
    {
        "file_class": "provider_task_sidecars",
        "handling": "blocked_without_status",
        "description": "Provider task keys may carry acquisition authority and need a narrower terminal status before deletion.",
    },
    {
        "file_class": "explicit_artifact_refs",
        "handling": "delete_if_unprotected",
        "description": "Concrete storage refs named by the manager plan are deleted when they resolve inside storage and are unprotected.",
    },
    {
        "file_class": "model_artifacts",
        "handling": "delete_if_scope_matched_and_unpromoted",
        "description": "Unpromoted model artifacts generated after the cutpoint are cleanup candidates.",
    },
    {
        "file_class": "replay_evaluation_settlement_promotion",
        "handling": "delete_if_scope_matched",
        "description": "Replay execution, post-replay, fold settlement, evaluation, and promotion-review run directories matching the model group are deleted.",
    },
    {
        "file_class": "dashboard_read_models",
        "handling": "delete_snapshots_refresh_latest",
        "description": "Timestamped dashboard/read-model snapshots are removed; latest read models are refreshed rather than deleted.",
    },
    {
        "file_class": "sql_rows",
        "handling": "blocked_pending_sql_executor",
        "description": "SQL rows are not filesystem artifacts and require owning table executors before reset reentry.",
    },
    {
        "file_class": "source_evidence",
        "handling": "retain",
        "description": "Protected source evidence is retained unless the reset scope explicitly includes a reviewed source-data mutation.",
    },
    {
        "file_class": "reset_lifecycle_receipts",
        "handling": "retain",
        "description": "Reset, lifecycle, delete, archive, restore, quarantine receipts and tombstones are retained audit evidence.",
    },
)

PROTECTED_RELATIVE_PREFIXES = (
    "storage/01_source_data/monthly_backfill/alpaca_bars",
    "storage/01_source_data/monthly_backfill/trading_economics_calendar_web",
    "storage/02_control_plane/runtime/model_group_rerun_resets",
    "storage/90_lifecycle",
)
PROTECTED_RELATIVE_PARTS = (
    "activation",
    "activations",
    "active_model",
    "active_models",
    "deactivation",
    "deactivations",
    "promoted",
    "promoted_model",
    "promoted_models",
)

REPLAY_RUN_ROOTS = (
    "replay_execution_runs",
    "post_replay_review_runs",
    "post_replay_attribution_runs",
    "post_replay_failure_triage_runs",
    "fold_settlement_runs",
    "model_evaluation_runs",
    "promotion_review_runs",
)

DASHBOARD_LATEST_READ_MODELS = (
    "current_system_status_summary.json",
    "historical_task_progress_summary.json",
    "temporal_explorer_summary.json",
    "realtime_signal_summary.json",
    "execution_realtime_trading_runtime_status.json",
    "model_readiness_summary.json",
    "model_promotion_posture_summary.json",
    "model_group_replay_review_summary.json",
)


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)


def _storage_dir(root: Path) -> Path:
    return root if root.name == "storage" else root / "storage"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_protected(root: Path, path: Path) -> bool:
    relative = _relative(root, path)
    if any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in PROTECTED_RELATIVE_PREFIXES):
        return True
    parts = Path(relative).parts
    if len(parts) >= 3 and parts[:3] == ("storage", "03_model_artifacts", "runtime"):
        return any(part in PROTECTED_RELATIVE_PARTS or part.startswith("promoted_") for part in parts)
    return False


def _has_protected_descendant(root: Path, path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(_is_protected(root, child) for child in path.rglob("*"))


def _inventory(root: Path, path: Path) -> dict[str, Any]:
    if path.is_dir():
        file_count = 0
        byte_count = 0
        for child in path.rglob("*"):
            if child.is_file():
                file_count += 1
                byte_count += child.stat().st_size
        return {
            "path": str(path),
            "relative_path": _relative(root, path),
            "path_type": "directory",
            "file_count": file_count,
            "byte_count": byte_count,
        }
    return {
        "path": str(path),
        "relative_path": _relative(root, path),
        "path_type": "file",
        "file_count": 1 if path.exists() else 0,
        "byte_count": path.stat().st_size if path.exists() else 0,
    }


def _scope(plan: Mapping[str, Any]) -> dict[str, Any]:
    reset_scope = plan.get("reset_scope")
    if isinstance(reset_scope, dict):
        return dict(reset_scope)
    affected_scope = dict(plan.get("affected_scope") or {})
    affected_scope.setdefault("scope_type", "model_group_fold")
    affected_scope.setdefault("state_path", "")
    affected_scope.setdefault("cutpoint", plan.get("cutpoint") or plan.get("change_origin") or {})
    return affected_scope


def _selector_scope(selector: Mapping[str, Any], fallback: Mapping[str, Any]) -> dict[str, Any]:
    value = selector.get("scope")
    if isinstance(value, dict):
        return dict(value)
    return dict(fallback)


def _stage_keys(plan: Mapping[str, Any]) -> tuple[str, ...]:
    keys: list[str] = []
    for selector in plan.get("generated_class_selectors") or []:
        if not isinstance(selector, dict):
            continue
        selector_scope = selector.get("scope")
        if isinstance(selector_scope, dict):
            keys.extend(str(key) for key in selector_scope.get("stage_keys") or [] if str(key))
    return tuple(dict.fromkeys(keys))


def _candidate_model_refs(plan: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for selector in plan.get("generated_class_selectors") or []:
        if not isinstance(selector, dict):
            continue
        selector_scope = selector.get("scope")
        if isinstance(selector_scope, dict):
            refs.extend(str(ref) for ref in selector_scope.get("candidate_model_refs") or [] if str(ref))
    if refs:
        return tuple(dict.fromkeys(refs))
    scope = _scope(plan)
    start = str(scope.get("start_month") or "")
    end = str(scope.get("end_month") or "")
    for symbol in scope.get("target_symbols") or []:
        refs.append(f"storage://trading-manager/model_group/{str(symbol).lower()}/{start}_{end}")
    return tuple(dict.fromkeys(refs))


def _scope_tokens(plan: Mapping[str, Any]) -> tuple[str, ...]:
    scope = _scope(plan)
    tokens: list[str] = []
    for key in ("start_month", "end_month", "state_path", "fold_id"):
        value = str(scope.get(key) or "")
        if value:
            tokens.append(value)
            tokens.append(Path(value).name)
    for symbol in scope.get("target_symbols") or []:
        value = str(symbol)
        tokens.extend([value, value.lower(), value.upper()])
    tokens.extend(_candidate_model_refs(plan))
    return tuple(dict.fromkeys(token for token in tokens if token and token != "."))


def _resolve_storage_ref(root: Path, ref: str) -> Path | None:
    clean = ref.split("#", 1)[0]
    if clean.startswith("storage://trading-storage/"):
        tail = clean.removeprefix("storage://trading-storage/")
        return root / tail
    if clean.startswith("storage://"):
        tail = clean.removeprefix("storage://")
        return _storage_dir(root) / tail
    path = Path(clean)
    if path.is_absolute():
        return path
    if clean.startswith("storage/"):
        return root / clean
    return None


def _add_delete_candidate(
    rows: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    *,
    root: Path,
    path: Path,
    file_class: str,
    selector_id: str,
    reason: str,
) -> None:
    if not path.exists():
        return
    if not _is_inside(root, path):
        blocked.append(
            {
                "file_class": file_class,
                "selector_id": selector_id,
                "path": str(path),
                "action": "blocked",
                "reason": "path_outside_storage_root",
            }
        )
        return
    if _is_protected(root, path) or _has_protected_descendant(root, path):
        blocked.append(
            {
                "file_class": file_class,
                "selector_id": selector_id,
                "path": str(path),
                "relative_path": _relative(root, path),
                "action": "retain",
                "reason": "protected_prefix_or_descendant",
            }
        )
        return
    inventory = _inventory(root, path)
    inventory.update(
        {
            "file_class": file_class,
            "selector_id": selector_id,
            "action": "delete",
            "reason": reason,
        }
    )
    rows.append(inventory)


def _selector_root_path(root: Path, selector: Mapping[str, Any], fallback: Path) -> Path:
    raw = str(selector.get("root_path") or "")
    if raw.startswith("sql://"):
        return fallback
    path = Path(raw) if raw else fallback
    if path.is_absolute():
        return path
    return root / path


def _iter_scope_matched_run_dirs(root: Path, plan: Mapping[str, Any]) -> Iterable[tuple[str, Path]]:
    base = _storage_dir(root) / "05_replay_datasets" / "promotion_replay_candidate_policy"
    refs = _candidate_model_refs(plan)
    if not base.exists() or not refs:
        return []
    matched: list[tuple[str, Path]] = []
    for run_root_name in REPLAY_RUN_ROOTS:
        run_root = base / run_root_name
        if not run_root.exists():
            continue
        for run in sorted(path for path in run_root.iterdir() if path.is_dir()):
            if _dir_mentions_any(run, refs):
                matched.append((run_root_name, run))
    return matched


def _dir_mentions_any(path: Path, needles: Sequence[str]) -> bool:
    for child in sorted(path.rglob("*.json")):
        if _file_mentions_any(child, needles):
            return True
    return False


def _file_mentions_any(path: Path, needles: Sequence[str]) -> bool:
    if any(needle in path.as_posix() for needle in needles):
        return True
    if path.stat().st_size > 5_000_000:
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(needle in content for needle in needles)


def _iter_scope_matched_files(root_path: Path, needles: Sequence[str]) -> tuple[Path, ...]:
    if not root_path.exists():
        return ()
    if root_path.is_file():
        return (root_path,) if _file_mentions_any(root_path, needles) else ()
    return tuple(path for path in sorted(root_path.rglob("*")) if path.is_file() and _file_mentions_any(path, needles))


def _planned_rows(root: Path, plan: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    delete_candidates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    refresh_required: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    storage_root = _storage_dir(root)
    stage_keys = _stage_keys(plan)
    scope_tokens = _scope_tokens(plan)

    for selector in plan.get("generated_class_selectors") or []:
        if not isinstance(selector, dict):
            continue
        selector_id = str(selector.get("selector_id") or "unknown_selector")
        root_class = str(selector.get("root_class") or "")
        action = str(selector.get("action") or "")
        reason = str(selector.get("reason") or plan.get("reason") or "rerun reset")
        selector_scope = _selector_scope(selector, _scope(plan))
        keys = tuple(str(key) for key in selector_scope.get("stage_keys") or stage_keys)

        if root_class in {"stage_receipts", "stage_logs"}:
            root_path = _selector_root_path(root, selector, storage_root / "02_control_plane" / "runtime" / root_class)
            for key in keys:
                stage_bucket = root_path / key
                matched_files = _iter_scope_matched_files(stage_bucket, scope_tokens)
                if stage_bucket.exists() and not matched_files:
                    unmatched.append(
                        {
                            "file_class": root_class,
                            "selector_id": selector_id,
                            "path": str(stage_bucket),
                            "reason": "stage_bucket_present_but_no_scope_matched_files",
                        }
                    )
                for path in matched_files:
                    _add_delete_candidate(
                        delete_candidates,
                        blocked,
                        root=root,
                        path=path,
                        file_class=root_class,
                        selector_id=selector_id,
                        reason=reason,
                    )
            continue

        if root_class == "task_progress_sidecars":
            root_path = _selector_root_path(root, selector, storage_root / "02_control_plane" / "runtime" / "task_progress")
            if not root_path.exists():
                unmatched.append(
                    {
                        "file_class": root_class,
                        "selector_id": selector_id,
                        "path": str(root_path),
                        "reason": "task_progress_root_absent",
                    }
                )
                continue
            for key in keys:
                for path in sorted(root_path.glob(f"*{key}*")):
                    matched_files = _iter_scope_matched_files(path, scope_tokens)
                    if path.exists() and not matched_files:
                        unmatched.append(
                            {
                                "file_class": root_class,
                                "selector_id": selector_id,
                                "path": str(path),
                                "reason": "task_progress_present_but_no_scope_match",
                            }
                        )
                    for matched in matched_files:
                        _add_delete_candidate(
                            delete_candidates,
                            blocked,
                            root=root,
                            path=matched,
                            file_class=root_class,
                            selector_id=selector_id,
                            reason=reason,
                        )
            continue

        if root_class == "provider_task_sidecars":
            blocked.append(
                {
                    "file_class": root_class,
                    "selector_id": selector_id,
                    "path": str(_selector_root_path(root, selector, storage_root / "02_control_plane" / "runtime" / "provider_task_keys")),
                    "action": "blocked",
                    "reason": "provider_task_key_status_required_before_delete",
                }
            )
            continue

        if root_class == "explicit_artifact_refs":
            refs = [str(ref) for ref in selector.get("candidate_refs") or []]
            if not refs:
                refs = [str(row.get("ref")) for row in plan.get("delete_set") or [] if isinstance(row, dict)]
            for ref in refs:
                if not ref or "#" in ref and ref.startswith("storage://02_control_plane/runtime/"):
                    continue
                path = _resolve_storage_ref(root, ref)
                if path is None:
                    unmatched.append(
                        {
                            "file_class": root_class,
                            "selector_id": selector_id,
                            "ref": ref,
                            "reason": "unsupported_or_non_file_ref",
                        }
                    )
                    continue
                _add_delete_candidate(
                    delete_candidates,
                    blocked,
                    root=root,
                    path=path,
                    file_class=root_class,
                    selector_id=selector_id,
                    reason=reason,
                )
            continue

        if root_class == "replay_datasets":
            for run_root_name, path in _iter_scope_matched_run_dirs(root, plan):
                _add_delete_candidate(
                    delete_candidates,
                    blocked,
                    root=root,
                    path=path,
                    file_class=f"replay_datasets/{run_root_name}",
                    selector_id=selector_id,
                    reason=reason,
                )
            continue

        if root_class == "model_artifacts":
            model_root = _selector_root_path(root, selector, storage_root / "03_model_artifacts" / "runtime")
            for matched_file in _iter_scope_matched_files(model_root, _candidate_model_refs(plan)):
                candidate_path = matched_file.parent if matched_file.parent != model_root else matched_file
                _add_delete_candidate(
                    delete_candidates,
                    blocked,
                    root=root,
                    path=candidate_path,
                    file_class="model_artifacts",
                    selector_id=selector_id,
                    reason=reason,
                )
            continue

        if root_class == "dashboard_cache":
            dashboard_root = _selector_root_path(root, selector, storage_root / "06_dashboard_cache")
            read_models_root = dashboard_root / "read_models"
            for latest_name in DASHBOARD_LATEST_READ_MODELS:
                latest_path = read_models_root / latest_name
                if latest_path.exists():
                    refresh_required.append(
                        {
                            "file_class": "dashboard_latest_read_model",
                            "selector_id": selector_id,
                            "path": str(latest_path),
                            "relative_path": _relative(root, latest_path),
                            "action": "refresh_required",
                            "reason": "latest read model must be refreshed from post-reset canonical evidence",
                        }
                    )
            for snapshots_root in sorted(read_models_root.glob("**/snapshots")):
                for snapshot in sorted(snapshots_root.iterdir()):
                    _add_delete_candidate(
                        delete_candidates,
                        blocked,
                        root=root,
                        path=snapshot,
                        file_class="dashboard_snapshot",
                        selector_id=selector_id,
                        reason=reason,
                    )
            continue

        if root_class == "sql_rows":
            blocked.append(
                {
                    "file_class": "sql_rows",
                    "selector_id": selector_id,
                    "path": str(selector.get("root_path") or "sql://"),
                    "action": "blocked",
                    "reason": "sql_rows_require_owning_table_executor",
                }
            )
            continue

        if action.startswith("blocked"):
            blocked.append(
                {
                    "file_class": root_class,
                    "selector_id": selector_id,
                    "path": str(selector.get("root_path") or ""),
                    "action": "blocked",
                    "reason": action,
                }
            )

    for selector in plan.get("protected_class_selectors") or []:
        if not isinstance(selector, dict):
            continue
        path = _selector_root_path(root, selector, storage_root)
        retained.append(
            {
                "file_class": str(selector.get("artifact_class") or "protected"),
                "selector_id": str(selector.get("selector_id") or "protected_selector"),
                "path": str(path),
                "relative_path": _relative(root, path) if path.exists() else None,
                "action": "retain",
                "reason": str(selector.get("reason") or "protected by reset plan"),
            }
        )

    unique_delete: dict[str, dict[str, Any]] = {}
    for row in delete_candidates:
        unique_delete[str(row["path"])] = row
    return {
        "delete_candidates": list(unique_delete.values()),
        "blocked": blocked,
        "retained": retained,
        "refresh_required": refresh_required,
        "unmatched": unmatched,
    }


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def build_rerun_reset_lifecycle_plan(
    *,
    root: Path,
    rerun_plan: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Expand a manager rerun plan into concrete storage file actions without mutation."""

    root = root.resolve()
    generated = generated_at or now_utc()
    rows = _planned_rows(root, rerun_plan)
    delete_byte_count = sum(int(row.get("byte_count") or 0) for row in rows["delete_candidates"])
    return {
        "contract_type": "storage_rerun_reset_lifecycle_plan",
        "generated_at": generated,
        "executor_version": EXECUTOR_VERSION,
        "root": str(root),
        "source_plan_id": rerun_plan.get("plan_id"),
        "source_rerun_id": rerun_plan.get("rerun_id"),
        "reset_scope": _scope(rerun_plan),
        "file_class_taxonomy": list(RERUN_RESET_FILE_CLASSES),
        "delete_candidates": rows["delete_candidates"],
        "blocked": rows["blocked"],
        "retained": rows["retained"],
        "refresh_required": rows["refresh_required"],
        "unmatched": rows["unmatched"],
        "summary": {
            "delete_candidate_count": len(rows["delete_candidates"]),
            "delete_candidate_byte_count": delete_byte_count,
            "blocked_count": len(rows["blocked"]),
            "retained_count": len(rows["retained"]),
            "refresh_required_count": len(rows["refresh_required"]),
            "unmatched_count": len(rows["unmatched"]),
            "mutation_performed": False,
            "requires_physical_clear_before_reentry": True,
            "broker_execution_performed": False,
            "account_mutation_performed": False,
            "model_activation_performed": False,
        },
    }


def execute_rerun_reset_lifecycle(
    *,
    root: Path,
    rerun_plan: Mapping[str, Any],
    apply: bool = False,
    approval_ref: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Optionally delete scoped generated files and write lifecycle receipts/tombstones."""

    root = root.resolve()
    if apply and not approval_ref:
        raise ValueError("approval_ref is required when applying rerun reset lifecycle deletion")
    generated = generated_at or now_utc()
    plan = build_rerun_reset_lifecycle_plan(root=root, rerun_plan=rerun_plan, generated_at=generated)
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if apply:
        for row in plan["delete_candidates"]:
            path = Path(str(row["path"]))
            if not path.exists():
                skipped.append({**row, "skip_reason": "already_absent"})
                continue
            if _is_protected(root, path) or _has_protected_descendant(root, path) or not _is_inside(root, path):
                skipped.append({**row, "skip_reason": "protected_or_outside_root"})
                continue
            deleted.append(dict(row))
            _delete_path(path)
    receipt = {
        "contract_type": "storage_rerun_reset_lifecycle_receipt",
        "generated_at": generated,
        "executor_version": EXECUTOR_VERSION,
        "root": str(root),
        "source_plan_id": plan.get("source_plan_id"),
        "source_rerun_id": plan.get("source_rerun_id"),
        "approval_ref": approval_ref,
        "dry_run": not apply,
        "mutation_performed": apply and bool(deleted),
        "delete_performed": apply and bool(deleted),
        "deleted_count": len(deleted),
        "deleted_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted),
        "delete_candidates_before_apply": plan["delete_candidates"],
        "deleted": deleted,
        "skipped": skipped,
        "blocked": plan["blocked"],
        "retained": plan["retained"],
        "refresh_required": plan["refresh_required"],
        "unmatched": plan["unmatched"],
        "file_class_taxonomy": plan["file_class_taxonomy"],
        "requires_dashboard_refresh": bool(plan["refresh_required"]),
        "requires_sql_cleanup": any(row.get("file_class") == "sql_rows" for row in plan["blocked"]),
        "broker_execution_performed": False,
        "account_mutation_performed": False,
        "model_activation_performed": False,
    }
    receipt_path = _receipt_path(root, str(plan.get("source_rerun_id") or "unknown_rerun"), generated)
    write_text_atomic(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = str(receipt_path)
    if apply and deleted:
        tombstone_path = _tombstone_path(root, str(plan.get("source_rerun_id") or "unknown_rerun"))
        for row in deleted:
            append_text_locked(
                tombstone_path,
                json.dumps(
                    {
                        "contract_type": "storage_rerun_reset_lifecycle_tombstone",
                        "deleted_at": generated,
                        "source_rerun_id": plan.get("source_rerun_id"),
                        "source_plan_id": plan.get("source_plan_id"),
                        "receipt_path": str(receipt_path),
                        **row,
                    },
                    sort_keys=True,
                )
                + "\n",
            )
        receipt["tombstone_path"] = str(tombstone_path)
        write_text_atomic(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def _receipt_path(root: Path, rerun_id: str, generated_at: str) -> Path:
    timestamp = generated_at.replace(":", "").replace("+00:00", "Z")
    return root / DEFAULT_RECEIPT_ROOT / _safe_id(rerun_id) / f"{timestamp}.receipt.json"


def _tombstone_path(root: Path, rerun_id: str) -> Path:
    return root / DEFAULT_TOMBSTONE_ROOT / f"{_safe_id(rerun_id)}.jsonl"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or execute storage cleanup for a model-group rerun reset.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--plan", type=Path, required=True, help="Manager model_group_rerun_plan JSON or result JSON containing a plan field.")
    parser.add_argument("--apply", action="store_true", help="Physically delete unprotected generated candidates and write tombstones.")
    parser.add_argument("--approval-ref", help="Operator or lifecycle decision reference authorizing --apply.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = _load_json(args.plan)
    rerun_plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
    receipt = execute_rerun_reset_lifecycle(
        root=args.root,
        rerun_plan=rerun_plan,
        apply=args.apply,
        approval_ref=args.approval_ref,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


__all__ = [
    "RERUN_RESET_FILE_CLASSES",
    "build_rerun_reset_lifecycle_plan",
    "execute_rerun_reset_lifecycle",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
