"""Storage-owned scheduled maintenance runner."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lifecycle import apply_retention_plan, plan_retention

DEFAULT_MAINTENANCE_OUTPUT = Path("storage/90_lifecycle/maintenance/storage_maintenance_summary.json")
DEFAULT_COMPACT_OUTPUT_ROOT = Path("storage/90_lifecycle/maintenance/compact_contracts")
MODEL_WORKER_STAGE_TYPES = {"model_generation", "model_evaluation", "promotion_review", "maintenance"}
COMPLETE_STATUSES = {"succeeded", "not_applicable"}
FOLD_STATE_GLOB = "model_training_fold_state_*.json"
FOLD_SCOPED_SOURCE_ROOT = Path("storage/01_source_data/fold_scoped")
TE_MONTHLY_SOURCE_ROOT = Path("storage/01_source_data/monthly_backfill/trading_economics_calendar_web")
TE_RUN_SIDE_PRODUCT_FILE_NAMES = {"completion_receipt.json", "request_manifest.json"}
PROOF_SIDECAR_FILE_NAMES = {"completion_receipt.json", "request_manifest.json"}
EVENT_FEED_MONTHLY_RECEIPT_ACTION_REF = "storage/01_source_data/monthly_backfill/event_feed_completion_receipts"
EVENT_FEED_MONTHLY_SOURCE_ARTIFACTS = {
    "alpaca_news": "equity_news.csv",
    "gdelt_news": "gdelt_article.csv",
    "release_calendar": "release_calendar.csv",
    "sec_company_financials": "sec_company_fact.csv",
    "trading_economics_calendar_web": "trading_economics_calendar_event.csv",
}
EVENT_FEED_SQL_ONLY_RUN_SIDECAR_SOURCE_IDS = {
    "alpaca_news",
    "gdelt_news",
    "release_calendar",
    "sec_company_financials",
}
EVENT_FEED_RUN_SIDECAR_FILE_NAMES = {
    "completion_receipt.json",
    "request_manifest.json",
    "schema.json",
}
PROOF_SIDECAR_AUDIT_ROOTS = (
    "storage/01_source_data",
    "storage/02_control_plane",
    "storage/03_model_artifacts",
    "storage/04_execution_artifacts",
    "storage/05_replay_datasets",
    "storage/06_dashboard_cache/read_models",
    "storage/90_lifecycle",
)
REPLAY_REVIEW_EVIDENCE_FILE_NAMES = {
    "decision_rows.jsonl",
    "entry_threshold_calibration.json",
    "model_candidate_selection_trace.jsonl",
    "replay_execution_receipt.json",
}
REPLAY_RUNTIME_SIDECAR_FILE_NAMES = {
    "candidate_replay_progress.jsonl",
    "option_feature_requirements.jsonl",
    "replay_progress.jsonl",
    "replay_resume_checkpoint.json",
    "replay_runtime_trace.jsonl",
}
REPLAY_REVIEW_EVIDENCE_MARKERS = {
    "baseline_comparison",
    "decision_rows",
    "model_candidate_selection_trace",
    "replay_execution_receipt",
    "replay_review",
    "scorecard",
}
ATTRIBUTION_RUNTIME_SIDECAR_FILE_NAMES = {
    "event_family_occurrence_scan.jsonl",
    "event_source_downloads.jsonl",
    "raw_event_downloads.jsonl",
}
RUNTIME_SIDECAR_NAME_MARKERS = {
    "checkpoint",
    "progress",
    "runtime_trace",
    "stderr",
    "stdout",
}
REFETCHABLE_EVENT_ORIGINAL_MARKERS = {
    "downloaded_event",
    "downloaded_news",
    "event_family_occurrence_scan",
    "event_news",
    "event_original",
    "event_source_download",
    "raw_event",
    "raw_news",
    "source_news",
}
CURRENT_MODEL_WORKER_FOLD_RE = re.compile(r"^fold_[a-z0-9]+_20\d{2}$")
LIFECYCLE_GAP_SELECTORS: tuple[dict[str, Any], ...] = (
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs",
        "artifact_class": "runtime_evidence",
        "issue": "closed_run_runtime_sidecars",
        "action": "compact",
        "final_handling_method": "delete_runtime_sidecars",
        "trigger_required": "replay_run_completed",
        "consumer_or_use": "model promotion replay audit and dashboard model posture",
        "required_followup": "write compact replay run manifest and preserve replay performance/review evidence before removing task progress, runtime trace, checkpoint, or log sidecars",
    },
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_review_runs",
        "artifact_class": "decision_evidence",
        "issue": "superseded_replay_review_runs",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "newer_review_run_completed_for_same_fold",
        "consumer_or_use": "model-group replay review dashboard and promotion audit",
        "required_followup": "write latest-per-fold review manifest and delete only older completed review runs for the same current candidate_fold_id",
    },
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_attribution_runs",
        "artifact_class": "decision_evidence",
        "issue": "closed_attribution_runtime_sidecars",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "post_replay_attribution_completed",
        "consumer_or_use": "residual event governance attribution review",
        "required_followup": "write attribution summary, preserve semantic event interpretations, and roll only raw scans/download sidecars",
    },
    {
        "artifact_ref": "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_failure_triage_runs",
        "artifact_class": "decision_evidence",
        "issue": "oversized_verbose_evidence",
        "action": "compact",
        "final_handling_method": "compress",
        "trigger_required": "failure_triage_closed",
        "consumer_or_use": "failure disposition audit",
        "required_followup": "write compact failure-triage decision contract before compressing verbose rows",
    },
    {
        "artifact_ref": "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/_manifests/recent_refresh_runs",
        "artifact_class": "runtime_evidence",
        "issue": "repeated_run_receipts",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "calendar_refresh_completed",
        "consumer_or_use": "TE source provenance and freshness dashboard",
        "required_followup": "write month-level provenance/read-model and preserve canonical TE source rows before rolling duplicate receipts",
    },
    {
        "artifact_ref": TE_MONTHLY_SOURCE_ROOT.as_posix(),
        "artifact_class": "runtime_evidence",
        "issue": "monthly_run_side_products",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "calendar_refresh_completed",
        "consumer_or_use": "TE canonical source payload provenance and freshness dashboard",
        "required_followup": "write month-level source provenance and roll duplicate run-local receipts/manifests without touching saved or cleaned TE source rows",
    },
    {
        "artifact_ref": EVENT_FEED_MONTHLY_RECEIPT_ACTION_REF,
        "artifact_class": "runtime_evidence",
        "issue": "redundant_monthly_completion_receipts",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "source_month_saved_payload_verified",
        "consumer_or_use": "event-feed readiness after consumers can read saved monthly source payloads",
        "required_followup": "write source-month receipt compaction manifest and delete only succeeded monthly receipts with matching saved payloads outside dashboard active inputs",
    },
    {
        "artifact_ref": "storage/04_execution_artifacts/runtime/realtime_monitor",
        "artifact_class": "runtime_evidence",
        "issue": "unbounded_timestamped_dirs",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "realtime_monitor_window_advanced",
        "consumer_or_use": "realtime signal dashboard and alert diagnostics",
        "required_followup": "write latest/current-window summary and preserve unresolved alert exceptions",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/model_05_option_expression",
        "artifact_class": "runtime_evidence",
        "issue": "per_request_task_key_sprawl",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "provider_stage_completed",
        "consumer_or_use": "provider retry and failure repair during active window",
        "required_followup": "write batch manifest and keep active, failed, retryable, or unresolved task keys",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/provider_task_keys",
        "artifact_class": "runtime_evidence",
        "issue": "per_request_task_key_sprawl",
        "action": "compact",
        "final_handling_method": "delete",
        "trigger_required": "provider_stage_completed",
        "consumer_or_use": "provider retry and failure repair during active window",
        "required_followup": "write provider batch manifest and keep active, failed, retryable, or unresolved task keys",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl",
        "artifact_class": "runtime_evidence",
        "issue": "append_only_log_as_read_model",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "scheduler_decision_window_closed",
        "consumer_or_use": "system status dashboard throughput view",
        "required_followup": "write scheduler rollup summary before rolling old JSONL segments",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/stage_coverage",
        "artifact_class": "derived_read_model",
        "issue": "timestamped_detail_without_aggregate",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "stage_coverage_window_closed",
        "consumer_or_use": "historical task progress dashboard",
        "required_followup": "write latest coverage plus aggregate before rolling detailed snapshots",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/stage_run_dashboard",
        "artifact_class": "derived_read_model",
        "issue": "timestamped_detail_without_aggregate",
        "action": "compact",
        "final_handling_method": "rolling_retention",
        "trigger_required": "stage_run_window_closed",
        "consumer_or_use": "system status dashboard",
        "required_followup": "write latest stage-run summary plus aggregate before rolling detailed snapshots",
    },
    {
        "artifact_ref": "storage/02_control_plane/runtime/model_02_target_state/input_materialization",
        "artifact_class": "debug_side_product",
        "issue": "unclear_lineage_rebuildability",
        "action": "retention_update",
        "final_handling_method": None,
        "handling_status": "insufficient_evidence",
        "trigger_required": "fold_or_run_closed",
        "consumer_or_use": "M02 input diagnosis",
        "required_followup": "prove SQL/source lineage and model references before choosing delete or compress",
    },
    {
        "artifact_ref": "storage/03_model_artifacts/runtime/model_05_alpha_confidence",
        "artifact_class": "decision_evidence",
        "issue": "unclear_canonical_owner",
        "action": "retention_update",
        "final_handling_method": None,
        "handling_status": "insufficient_evidence",
        "trigger_required": "model_artifact_role_classified",
        "consumer_or_use": "model evaluation and promotion evidence",
        "required_followup": "classify as canonical model evidence, compressible cold evidence, or rebuildable runtime output",
    },
)
ORDERED_STORAGE_ROOTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "01_source_data",
        "storage/01_source_data",
        "durable_source",
        "Reusable M01/M02 source foundations plus explicitly fold-scoped target/source artifacts.",
    ),
    ("02_control_plane", "storage/02_control_plane", "durable_control", "Manager task state, workflow state, receipts, and control-plane artifacts."),
    ("03_model_artifacts", "storage/03_model_artifacts", "durable_model", "Model training, diagnostics, research, and promotion-adjacent artifacts."),
    ("04_execution_artifacts", "storage/04_execution_artifacts", "durable_execution", "Realtime observation, shadow/live, and execution-side artifacts."),
    ("05_replay_datasets", "storage/05_replay_datasets", "durable_replay", "Frozen replay datasets, acquisition plans, and replay inputs."),
    ("06_dashboard_cache", "storage/06_dashboard_cache", "managed_cache", "Dashboard read-model current/schema cache."),
    ("90_lifecycle", "storage/90_lifecycle", "lifecycle_control", "Lifecycle plans, indexes, protected sets, receipts, archives, cache, staging, and logs."),
)


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class StorageMaintenanceSummary:
    """Summary receipt for one scheduled storage maintenance pass."""

    contract_type: str
    generated_at_utc: str
    root: str
    local_retention_enabled: bool
    local_retention_apply: bool
    local_retention_summary: dict[str, int]
    storage_root_inventory_summary: dict[str, Any]
    storage_root_inventory: tuple[dict[str, Any], ...]
    manager_root: str | None
    fold_monitor_enabled: bool
    completed_fold_count: int
    completed_fold_ids: tuple[str, ...]
    fold_backup_candidates: tuple[dict[str, Any], ...]
    fold_source_cleanup_candidates: tuple[dict[str, Any], ...]
    fold_source_cleanup_candidate_count: int
    lifecycle_gap_audit_summary: dict[str, Any]
    lifecycle_gap_findings: tuple[dict[str, Any], ...]
    lifecycle_gap_action_summary: dict[str, Any]
    lifecycle_gap_action_receipts: tuple[dict[str, Any], ...]
    proof_sidecar_audit_summary: dict[str, Any]
    proof_sidecar_audit_findings: tuple[dict[str, Any], ...]
    fold_sql_backup_phase_status: str
    fold_source_cleanup_phase_status: str
    deletion_phase_status: str
    provider_calls_performed: bool
    model_activation_performed: bool
    broker_execution_performed: bool
    account_mutation_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "generated_at_utc": self.generated_at_utc,
            "root": self.root,
            "local_retention_enabled": self.local_retention_enabled,
            "local_retention_apply": self.local_retention_apply,
            "local_retention_summary": self.local_retention_summary,
            "storage_root_inventory_summary": self.storage_root_inventory_summary,
            "storage_root_inventory": list(self.storage_root_inventory),
            "manager_root": self.manager_root,
            "fold_monitor_enabled": self.fold_monitor_enabled,
            "completed_fold_count": self.completed_fold_count,
            "completed_fold_ids": list(self.completed_fold_ids),
            "fold_backup_candidates": list(self.fold_backup_candidates),
            "fold_source_cleanup_candidates": list(self.fold_source_cleanup_candidates),
            "fold_source_cleanup_candidate_count": self.fold_source_cleanup_candidate_count,
            "lifecycle_gap_audit_summary": self.lifecycle_gap_audit_summary,
            "lifecycle_gap_findings": list(self.lifecycle_gap_findings),
            "lifecycle_gap_action_summary": self.lifecycle_gap_action_summary,
            "lifecycle_gap_action_receipts": list(self.lifecycle_gap_action_receipts),
            "proof_sidecar_audit_summary": self.proof_sidecar_audit_summary,
            "proof_sidecar_audit_findings": list(self.proof_sidecar_audit_findings),
            "fold_sql_backup_phase_status": self.fold_sql_backup_phase_status,
            "fold_source_cleanup_phase_status": self.fold_source_cleanup_phase_status,
            "deletion_phase_status": self.deletion_phase_status,
            "provider_calls_performed": self.provider_calls_performed,
            "model_activation_performed": self.model_activation_performed,
            "broker_execution_performed": self.broker_execution_performed,
            "account_mutation_performed": self.account_mutation_performed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _build_storage_root_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    inventory: list[dict[str, Any]] = []
    for root_id, relative, lifecycle_role, description in ORDERED_STORAGE_ROOTS:
        base = root / relative
        file_count = 0
        directory_count = 0
        byte_count = 0
        if base.exists():
            if base.is_file() and not base.is_symlink():
                file_count = 1
                byte_count = base.stat().st_size
            elif base.is_dir():
                for path in base.rglob("*"):
                    if path.is_symlink():
                        continue
                    if path.is_dir():
                        directory_count += 1
                    elif path.is_file():
                        file_count += 1
                        try:
                            byte_count += path.stat().st_size
                        except OSError:
                            pass
        inventory.append(
            {
                "root_id": root_id,
                "path": relative,
                "exists": base.exists(),
                "lifecycle_role": lifecycle_role,
                "description": description,
                "file_count": file_count,
                "directory_count": directory_count,
                "byte_count": byte_count,
            }
        )
    return tuple(inventory)


def _storage_root_inventory_summary(inventory: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "contract_type": "storage_root_inventory_summary",
        "root_count": len(inventory),
        "existing_root_count": sum(1 for row in inventory if row.get("exists")),
        "total_file_count": sum(int(row.get("file_count") or 0) for row in inventory),
        "total_directory_count": sum(int(row.get("directory_count") or 0) for row in inventory),
        "total_byte_count": sum(int(row.get("byte_count") or 0) for row in inventory),
        "managed_root_ids": [str(row.get("root_id")) for row in inventory],
    }


def _path_inventory(path: Path) -> dict[str, Any]:
    """Return bounded inventory evidence for a lifecycle selector target."""

    file_count = 0
    directory_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    if not path.exists():
        return {
            "exists": False,
            "file_count": 0,
            "directory_count": 0,
            "byte_count": 0,
            "largest_file_path": None,
            "largest_file_bytes": 0,
        }
    paths = (path,) if path.is_file() else path.rglob("*")
    for candidate in paths:
        if candidate.is_symlink():
            continue
        if candidate.is_dir():
            directory_count += 1
            continue
        if not candidate.is_file():
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        file_count += 1
        byte_count += size
        if size > largest_file_bytes:
            largest_file_bytes = size
            largest_file_path = candidate.as_posix()
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _task_key_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    file_count = 0
    byte_count = 0
    parent_dirs: set[str] = set()
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for candidate in path.rglob("task_key.json"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        file_count += 1
        byte_count += size
        parent_dirs.add(candidate.parent.as_posix())
        if size > largest_file_bytes:
            largest_file_bytes = size
            largest_file_path = candidate.as_posix()
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": len(parent_dirs),
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _named_file_inventory(path: Path, names: set[str]) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    file_count = 0
    directory_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    parent_dirs: set[str] = set()
    for candidate in path.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file() or candidate.name not in names:
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        file_count += 1
        byte_count += size
        parent_dirs.add(candidate.parent.as_posix())
        if size > largest_file_bytes:
            largest_file_bytes = size
            largest_file_path = candidate.as_posix()
    directory_count = len(parent_dirs)
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _rolling_dir_inventory(path: Path, *, retain_recent_count: int) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    runs = _run_dirs(path)
    candidates = runs[: max(len(runs) - retain_recent_count, 0)]
    file_count = 0
    directory_count = len(candidates)
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for run in candidates:
        inventory = _path_inventory(run)
        file_count += int(inventory["file_count"])
        byte_count += int(inventory["byte_count"])
        if int(inventory["largest_file_bytes"]) > largest_file_bytes:
            largest_file_bytes = int(inventory["largest_file_bytes"])
            largest_file_path = inventory["largest_file_path"]
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _named_file_rolling_inventory(path: Path, names: set[str], *, retain_recent_count: int) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    runs = _run_dirs(path)
    retained = {run for run in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    candidates = [run for run in runs if run not in retained]
    file_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for run in candidates:
        inventory = _named_file_inventory(run, names)
        file_count += int(inventory["file_count"])
        byte_count += int(inventory["byte_count"])
        if int(inventory["largest_file_bytes"]) > largest_file_bytes:
            largest_file_bytes = int(inventory["largest_file_bytes"])
            largest_file_path = inventory["largest_file_path"]
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": len([run for run in candidates if _named_file_inventory(run, names)["file_count"]]),
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _latest_matching_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.glob(pattern) if path.is_file() and not path.is_symlink()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.as_posix()))


def _proof_dashboard_active_input_refs(root: Path) -> set[str]:
    refs: set[str] = set()
    exact_paths = (
        "storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl",
        "storage/02_control_plane/runtime/historical_scheduler_state.json",
        "storage/04_execution_artifacts/runtime/realtime_trading_runtime/runtime_status.json",
    )
    for relative in exact_paths:
        path = root / relative
        if path.exists() and path.is_file() and not path.is_symlink():
            refs.add(relative)
    for pattern_root, pattern in (
        ("storage/02_control_plane/runtime", "model_training_workflow_state_*.json"),
        ("storage/02_control_plane/runtime/stage_coverage", "*.json"),
        ("storage/02_control_plane/runtime/stage_run_dashboard", "*.json"),
        ("storage/04_execution_artifacts/runtime/realtime_monitor", "**/loop_receipt.json"),
        ("storage/04_execution_artifacts/runtime/realtime_monitor", "**/cycle_*.json"),
        (TE_MONTHLY_SOURCE_ROOT.as_posix(), "**/completion_receipt.json"),
    ):
        latest = _latest_matching_file(root / pattern_root, pattern)
        if latest is not None:
            refs.add(_relative_path(root, latest))
    read_model_root = root / "storage/06_dashboard_cache/read_models"
    if read_model_root.exists():
        refs.update(
            _relative_path(root, path)
            for path in sorted(read_model_root.glob("*.json"))
            if path.is_file() and not path.is_symlink()
        )
    return refs


def _is_top_level_dashboard_read_model(relative: str) -> bool:
    parts = Path(relative).parts
    return len(parts) == 4 and parts[:3] == ("storage", "06_dashboard_cache", "read_models") and relative.endswith(".json")


def _is_te_canonical_source_payload(relative: str) -> bool:
    parts = Path(relative).parts
    return (
        len(parts) >= 7
        and parts[:4] == ("storage", "01_source_data", "monthly_backfill", "trading_economics_calendar_web")
        and any(part in {"saved", "cleaned"} for part in parts)
    )


def _is_durable_lifecycle_boundary(relative: str) -> bool:
    normalized = relative.lower().replace("-", "_")
    return any(
        token in normalized
        for token in (
            "archive_manifest",
            "archive_receipt",
            "compression_manifest",
            "compression_receipt",
            "delete_receipt",
            "deletion_receipt",
            "lifecycle_decision",
            "lifecycle_gap_action_receipt",
            "quarantine_recheck",
            "restore_receipt",
            "storage_lifecycle_plan",
            "tombstone",
        )
    )


def _proof_sidecar_bucket(*, root: Path, path: Path, dashboard_active_refs: set[str]) -> str | None:
    relative = _relative_path(root, path)
    normalized = relative.lower().replace("\\", "/")
    name = path.name.lower()
    stem = path.stem.lower()
    if relative in dashboard_active_refs:
        return "dashboard_active_input_retained"
    if _is_top_level_dashboard_read_model(relative):
        return "dashboard_latest_retained"
    if _is_te_canonical_source_payload(relative):
        return "canonical_source_retained"
    if _is_durable_lifecycle_boundary(relative):
        return "durable_boundary_evidence_retained"
    if "event_interpretations" in normalized or "event_interpretation" in normalized:
        return "formal_event_interpretation_retained"
    if normalized.startswith("storage/05_replay_datasets/") and (
        name in REPLAY_REVIEW_EVIDENCE_FILE_NAMES or any(marker in stem for marker in REPLAY_REVIEW_EVIDENCE_MARKERS)
    ):
        return "replay_review_evidence_retained"
    if any(marker in normalized for marker in REFETCHABLE_EVENT_ORIGINAL_MARKERS):
        return "refetchable_event_original_candidate"
    if name in PROOF_SIDECAR_FILE_NAMES:
        return "redundant_proof_sidecar_candidate"
    if name.endswith(".log") or any(marker in name for marker in RUNTIME_SIDECAR_NAME_MARKERS):
        return "runtime_sidecar_candidate"
    return None


def _is_proof_sidecar_audit_target(relative: str, filename: str) -> bool:
    normalized = relative.lower().replace("\\", "/")
    stem = Path(filename).stem.lower()
    if filename in PROOF_SIDECAR_FILE_NAMES:
        return True
    if filename.endswith(".log") or any(marker in filename for marker in RUNTIME_SIDECAR_NAME_MARKERS):
        return True
    if _is_top_level_dashboard_read_model(relative):
        return True
    if _is_te_canonical_source_payload(relative):
        return True
    if _is_durable_lifecycle_boundary(relative):
        return True
    if "event_interpretations" in normalized or "event_interpretation" in normalized:
        return True
    if normalized.startswith("storage/05_replay_datasets/") and (
        filename in REPLAY_REVIEW_EVIDENCE_FILE_NAMES or any(marker in stem for marker in REPLAY_REVIEW_EVIDENCE_MARKERS)
    ):
        return True
    return any(marker in normalized for marker in REFETCHABLE_EVENT_ORIGINAL_MARKERS)


def _iter_proof_sidecar_audit_files(root: Path, *, dashboard_active_refs: set[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for relative in sorted(dashboard_active_refs):
        path = root / relative
        if path.exists() and path.is_file() and not path.is_symlink():
            files.append(path)
            seen.add(path)
    for relative in PROOF_SIDECAR_AUDIT_ROOTS:
        base = root / relative
        if not base.exists():
            continue
        if base.is_file():
            candidates = [base]
        else:
            candidates = []
            for directory, dirnames, filenames in os.walk(base):
                dirnames.sort()
                for filename in sorted(filenames):
                    path = Path(directory) / filename
                    try:
                        candidate_relative = _relative_path(root, path)
                    except OSError:
                        continue
                    if _is_proof_sidecar_audit_target(candidate_relative, filename.lower()):
                        candidates.append(path)
        for path in candidates:
            if path.is_symlink() or not path.is_file() or path in seen:
                continue
            if _proof_sidecar_bucket(root=root, path=path, dashboard_active_refs=dashboard_active_refs) is not None:
                files.append(path)
                seen.add(path)
    return sorted(files)


def audit_proof_sidecars(*, root: Path) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Bucket proof/runtime sidecars without hashing or mutating payloads."""

    root = root.resolve()
    dashboard_active_refs = _proof_dashboard_active_input_refs(root)
    by_bucket: dict[str, dict[str, Any]] = {}
    for path in _iter_proof_sidecar_audit_files(root, dashboard_active_refs=dashboard_active_refs):
        bucket = _proof_sidecar_bucket(root=root, path=path, dashboard_active_refs=dashboard_active_refs)
        if bucket is None:
            continue
        relative = _relative_path(root, path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        row = by_bucket.setdefault(
            bucket,
            {
                "contract_type": "storage_proof_sidecar_bucket_finding",
                "bucket": bucket,
                "file_count": 0,
                "byte_count": 0,
                "largest_file_path": None,
                "largest_file_bytes": 0,
                "sample_paths": [],
                "mutation_performed": False,
            },
        )
        row["file_count"] += 1
        row["byte_count"] += size
        if size > int(row["largest_file_bytes"] or 0):
            row["largest_file_bytes"] = size
            row["largest_file_path"] = relative
        if len(row["sample_paths"]) < 10:
            row["sample_paths"].append(relative)

    findings: list[dict[str, Any]] = []
    retained_buckets = {
        "canonical_source_retained",
        "dashboard_active_input_retained",
        "dashboard_latest_retained",
        "durable_boundary_evidence_retained",
        "formal_event_interpretation_retained",
        "replay_review_evidence_retained",
    }
    candidate_buckets = {
        "redundant_proof_sidecar_candidate",
        "refetchable_event_original_candidate",
        "runtime_sidecar_candidate",
    }
    for bucket, row in sorted(by_bucket.items()):
        if bucket in retained_buckets:
            row["handling_status"] = "retained"
            row["review_required"] = False
        elif bucket in candidate_buckets:
            row["handling_status"] = "cleanup_candidate"
            row["review_required"] = True
        else:
            row["handling_status"] = "manual_review_required"
            row["review_required"] = True
        findings.append(row)

    summary = {
        "contract_type": "storage_proof_sidecar_audit_summary",
        "bucket_count": len(findings),
        "total_file_count": sum(int(row["file_count"]) for row in findings),
        "total_byte_count": sum(int(row["byte_count"]) for row in findings),
        "cleanup_candidate_file_count": sum(
            int(row["file_count"]) for row in findings if row["handling_status"] == "cleanup_candidate"
        ),
        "cleanup_candidate_byte_count": sum(
            int(row["byte_count"]) for row in findings if row["handling_status"] == "cleanup_candidate"
        ),
        "retained_file_count": sum(int(row["file_count"]) for row in findings if row["handling_status"] == "retained"),
        "retained_byte_count": sum(int(row["byte_count"]) for row in findings if row["handling_status"] == "retained"),
        "dashboard_active_input_count": len(dashboard_active_refs),
        "mutation_performed": False,
    }
    return summary, tuple(findings)


def _empty_proof_sidecar_audit_summary(*, skipped: bool) -> dict[str, Any]:
    return {
        "contract_type": "storage_proof_sidecar_audit_summary",
        "bucket_count": 0,
        "total_file_count": 0,
        "total_byte_count": 0,
        "cleanup_candidate_file_count": 0,
        "cleanup_candidate_byte_count": 0,
        "retained_file_count": 0,
        "retained_byte_count": 0,
        "dashboard_active_input_count": 0,
        "mutation_performed": False,
        "skipped": skipped,
    }


def _replay_execution_gap_inventory(path: Path, *, retain_recent_count: int) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    runs = _run_dirs(path)
    retained = {run for run in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    file_count = 0
    directory_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for run in runs:
        if run in retained:
            continue
        receipt = _read_json_object(run / "replay_execution_receipt.json") or {}
        validation_status = str(receipt.get("validation_status") or "").lower()
        if validation_status not in {"passed", "succeeded", "success"}:
            continue
        inventory = _named_file_inventory(run, REPLAY_RUNTIME_SIDECAR_FILE_NAMES)
        if int(inventory["file_count"]) > 0:
            directory_count += 1
        file_count += int(inventory["file_count"])
        byte_count += int(inventory["byte_count"])
        if int(inventory["largest_file_bytes"]) > largest_file_bytes:
            largest_file_bytes = int(inventory["largest_file_bytes"])
            largest_file_path = inventory["largest_file_path"]
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _current_candidate_fold_id(receipt: Mapping[str, Any]) -> str:
    fold_id = str(receipt.get("candidate_fold_id") or receipt.get("fold_id") or "").strip().lower()
    return fold_id if CURRENT_MODEL_WORKER_FOLD_RE.fullmatch(fold_id) else ""


def _post_replay_review_sort_value(run: Path, receipt: Mapping[str, Any]) -> str:
    return str(receipt.get("completed_at_utc") or receipt.get("created_at_utc") or run.name)


def _superseded_post_replay_review_runs(path: Path) -> tuple[tuple[Path, dict[str, Any]], ...]:
    latest_by_fold: dict[str, tuple[Path, dict[str, Any]]] = {}
    superseded: list[tuple[Path, dict[str, Any]]] = []
    for run in _run_dirs(path):
        receipt = _read_json_object(run / "post_replay_review_receipt.json") or {}
        fold_id = _current_candidate_fold_id(receipt)
        if not fold_id:
            continue
        current = latest_by_fold.get(fold_id)
        if current is None:
            latest_by_fold[fold_id] = (run, receipt)
            continue
        if _post_replay_review_sort_value(run, receipt) >= _post_replay_review_sort_value(current[0], current[1]):
            superseded.append(current)
            latest_by_fold[fold_id] = (run, receipt)
        else:
            superseded.append((run, receipt))
    return tuple(superseded)


def _post_replay_review_duplicate_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    file_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    superseded = _superseded_post_replay_review_runs(path)
    for run, _receipt in superseded:
        inventory = _path_inventory(run)
        file_count += int(inventory["file_count"])
        byte_count += int(inventory["byte_count"])
        if int(inventory["largest_file_bytes"]) > largest_file_bytes:
            largest_file_bytes = int(inventory["largest_file_bytes"])
            largest_file_path = inventory["largest_file_path"]
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": len(superseded),
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _realtime_monitor_gap_inventory(path: Path, *, retain_recent_count: int) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    runs = _run_dirs(path)
    retained = {run for run in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    candidates: list[Path] = []
    for run in runs:
        if run in retained:
            continue
        if _realtime_loop_has_exception(_read_json_object(run / "loop_receipt.json")):
            continue
        candidates.append(run)
    file_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for run in candidates:
        inventory = _path_inventory(run)
        file_count += int(inventory["file_count"])
        byte_count += int(inventory["byte_count"])
        if int(inventory["largest_file_bytes"]) > largest_file_bytes:
            largest_file_bytes = int(inventory["largest_file_bytes"])
            largest_file_path = inventory["largest_file_path"]
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": len(candidates),
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _te_monthly_run_dirs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    runs: list[Path] = []
    for month_dir in sorted(path.iterdir()):
        if not month_dir.is_dir() or month_dir.is_symlink() or len(month_dir.name) != 7 or month_dir.name[4] != "-":
            continue
        run_root = month_dir / "runs"
        if not run_root.exists():
            continue
        runs.extend(candidate for candidate in run_root.iterdir() if candidate.is_dir() and not candidate.is_symlink())
    return sorted(runs, key=lambda item: (item.parent.parent.name, item.name))


def _te_monthly_run_side_product_inventory(path: Path, *, retain_recent_count: int) -> dict[str, Any]:
    if not path.exists():
        return _path_inventory(path)
    runs = _te_monthly_run_dirs(path)
    retained = {run for run in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    file_count = 0
    directory_count = 0
    byte_count = 0
    largest_file_path: str | None = None
    largest_file_bytes = 0
    for run in runs:
        if run in retained:
            continue
        run_file_count = 0
        for name in sorted(TE_RUN_SIDE_PRODUCT_FILE_NAMES):
            candidate = run / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                size = candidate.stat().st_size
            except OSError:
                continue
            file_count += 1
            run_file_count += 1
            byte_count += size
            if size > largest_file_bytes:
                largest_file_bytes = size
                largest_file_path = candidate.as_posix()
        if run_file_count:
            directory_count += 1
    return {
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "byte_count": byte_count,
        "largest_file_path": largest_file_path,
        "largest_file_bytes": largest_file_bytes,
    }


def _lifecycle_gap_inventory(root: Path, artifact_ref: str) -> dict[str, Any]:
    path = root / artifact_ref
    if artifact_ref.endswith("replay_execution_runs"):
        return _replay_execution_gap_inventory(path, retain_recent_count=3)
    if artifact_ref.endswith("post_replay_review_runs"):
        return _post_replay_review_duplicate_inventory(path)
    if artifact_ref.endswith("post_replay_attribution_runs"):
        return _named_file_rolling_inventory(path, ATTRIBUTION_RUNTIME_SIDECAR_FILE_NAMES, retain_recent_count=3)
    if artifact_ref.endswith("post_replay_failure_triage_runs"):
        return _named_file_inventory(path, {"failure_triage_rows.jsonl"})
    if artifact_ref.endswith("_manifests/recent_refresh_runs"):
        return _rolling_dir_inventory(path, retain_recent_count=24)
    if artifact_ref == TE_MONTHLY_SOURCE_ROOT.as_posix():
        return _te_monthly_run_side_product_inventory(path, retain_recent_count=24)
    if artifact_ref.endswith("realtime_monitor"):
        return _realtime_monitor_gap_inventory(path, retain_recent_count=100)
    if artifact_ref.endswith("provider_task_keys") or artifact_ref.endswith("model_05_option_expression"):
        return _task_key_inventory(path)
    return _path_inventory(path)


def detect_lifecycle_gap_findings(*, root: Path) -> tuple[dict[str, Any], ...]:
    """Report known unbounded lifecycle classes without mutating storage."""

    findings: list[dict[str, Any]] = []
    for selector in LIFECYCLE_GAP_SELECTORS:
        artifact_ref = selector["artifact_ref"]
        inventory = _lifecycle_gap_inventory(root, artifact_ref)
        if not inventory["exists"] or int(inventory["file_count"]) == 0:
            continue
        findings.append(
            {
                "contract_type": "storage_lifecycle_gap_finding",
                "artifact_ref": artifact_ref,
                "artifact_class": selector["artifact_class"],
                "issue": selector["issue"],
                "action": selector["action"],
                "final_handling_method": selector["final_handling_method"],
                "handling_status": selector.get("handling_status", "selected"),
                "trigger_required": selector["trigger_required"],
                "consumer_or_use": selector["consumer_or_use"],
                "required_followup": selector["required_followup"],
                "file_count": inventory["file_count"],
                "directory_count": inventory["directory_count"],
                "byte_count": inventory["byte_count"],
                "largest_file_path": inventory["largest_file_path"],
                "largest_file_bytes": inventory["largest_file_bytes"],
                "mutation_performed": False,
                "review_required": True,
            }
        )
    return tuple(findings)


def _lifecycle_gap_audit_summary(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "contract_type": "storage_lifecycle_gap_audit_summary",
        "finding_count": len(findings),
        "total_byte_count": sum(int(row.get("byte_count") or 0) for row in findings),
        "total_file_count": sum(int(row.get("file_count") or 0) for row in findings),
        "by_final_handling_method": {
            method: sum(1 for row in findings if row.get("final_handling_method") == method)
            for method in ("delete", "compress", "rolling_retention")
        },
        "pending_final_handling_count": sum(1 for row in findings if not row.get("final_handling_method")),
        "mutation_performed": False,
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_object(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _directory_inventory(path: Path, *, root: Path) -> dict[str, Any]:
    inventory = _path_inventory(path)
    inventory["artifact_ref"] = _relative_path(root, path)
    return inventory


def _run_dirs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted((candidate for candidate in path.iterdir() if candidate.is_dir() and not candidate.is_symlink()), key=lambda item: item.name)


def _file_row(path: Path, *, root: Path, include_hash: bool = False) -> dict[str, Any]:
    stat = path.stat()
    row: dict[str, Any] = {
        "path": _relative_path(root, path),
        "byte_count": stat.st_size,
    }
    if include_hash:
        row["sha256"] = _sha256_file(path)
    return row


def _delete_file(path: Path, *, root: Path, include_hash: bool) -> dict[str, Any]:
    row = _file_row(path, root=root, include_hash=include_hash)
    path.unlink()
    row["mutation"] = "deleted"
    return row


def _delete_tree(path: Path, *, root: Path) -> dict[str, Any]:
    inventory = _directory_inventory(path, root=root)
    shutil.rmtree(path)
    inventory["mutation"] = "deleted_tree"
    return inventory


def _compress_file(path: Path, *, root: Path, include_hash: bool) -> dict[str, Any]:
    source = _file_row(path, root=root, include_hash=include_hash)
    output_path = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as source_handle, gzip.open(output_path, "wb", compresslevel=9) as output_handle:
        shutil.copyfileobj(source_handle, output_handle)
    compressed = _file_row(output_path, root=root, include_hash=include_hash)
    path.unlink()
    return {
        "source": source,
        "compressed": compressed,
        "compression_method": "gzip",
        "mutation": "compressed_and_deleted_source",
    }


def _compact_replay_execution_runs(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    retain_recent_count: int,
    include_hashes: bool,
) -> dict[str, Any]:
    artifact_root = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs"
    runs = _run_dirs(artifact_root)
    retained = {path for path in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    run_rows: list[dict[str, Any]] = []
    deleted_rows: list[dict[str, Any]] = []
    skipped_count = 0
    candidate_count = 0
    for run in runs:
        receipt = _read_json_object(run / "replay_execution_receipt.json") or {}
        runtime_sidecar_files = [
            path for path in sorted(run.iterdir()) if path.is_file() and path.name in REPLAY_RUNTIME_SIDECAR_FILE_NAMES
        ]
        review_evidence_files = [
            path for path in sorted(run.iterdir()) if path.is_file() and path.name in REPLAY_REVIEW_EVIDENCE_FILE_NAMES
        ]
        if run not in retained:
            candidate_count += len(runtime_sidecar_files)
        validation_status = str(receipt.get("validation_status") or "").lower()
        row = {
            "run_id": run.name,
            "run_ref": _relative_path(root, run),
            "validation_status": validation_status or None,
            "candidate_model_ref": receipt.get("candidate_model_ref"),
            "candidate_fold_id": receipt.get("candidate_fold_id"),
            "decision_row_count": receipt.get("decision_row_count"),
            "target_refs": receipt.get("target_refs"),
            "runtime_sidecar_file_count": len(runtime_sidecar_files),
            "runtime_sidecar_byte_count": sum(path.stat().st_size for path in runtime_sidecar_files),
            "review_evidence_file_count": len(review_evidence_files),
            "review_evidence_byte_count": sum(path.stat().st_size for path in review_evidence_files),
            "review_evidence_preserved": True,
            "retained_full_runtime_sidecars": run in retained,
        }
        if apply and run not in retained and validation_status in {"passed", "succeeded", "success"}:
            for path in runtime_sidecar_files:
                deleted_rows.append(_delete_file(path, root=root, include_hash=include_hashes))
        elif runtime_sidecar_files and run not in retained:
            skipped_count += len(runtime_sidecar_files)
        run_rows.append(row)
    compact = {
        "contract_type": "storage_replay_execution_compact_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "run_count": len(runs),
        "recent_full_run_retention_count": retain_recent_count,
        "run_summaries": run_rows,
        "preserved_review_evidence_file_names": sorted(REPLAY_REVIEW_EVIDENCE_FILE_NAMES),
        "deleted_runtime_sidecar_file_count": len(deleted_rows),
        "deleted_runtime_sidecar_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "skipped_runtime_sidecar_file_count": skipped_count,
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "replay_execution_runs_compact_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_delete_runtime_sidecars",
        "final_handling_method": "delete_runtime_sidecars",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": candidate_count,
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_runtime_sidecar_byte_count"],
        "skipped_count": skipped_count,
        "mutation_performed": bool(deleted_rows),
    }


def _compact_post_replay_review_runs(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
) -> dict[str, Any]:
    artifact_root = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_review_runs"
    superseded = _superseded_post_replay_review_runs(artifact_root)
    run_rows: list[dict[str, Any]] = []
    deleted_rows: list[dict[str, Any]] = []
    for run, receipt in superseded:
        row = _directory_inventory(run, root=root)
        row.update(
            {
                "run_id": run.name,
                "candidate_fold_id": _current_candidate_fold_id(receipt),
                "candidate_model_ref": receipt.get("candidate_model_ref"),
                "replay_execution_run_id": receipt.get("replay_execution_run_id"),
                "created_at_utc": receipt.get("created_at_utc"),
                "completed_at_utc": receipt.get("completed_at_utc"),
                "superseded_by_scope": "latest_completed_post_replay_review_run_for_same_candidate_fold_id",
            }
        )
        run_rows.append(row)
        if apply:
            deleted_rows.append(_delete_tree(run, root=root))
    compact = {
        "contract_type": "storage_post_replay_review_compact_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "retention_rule": "keep_latest_completed_run_per_current_candidate_fold_id",
        "superseded_run_count": len(run_rows),
        "superseded_runs": run_rows,
        "deleted_run_count": len(deleted_rows),
        "deleted_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "post_replay_review_latest_per_fold_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_delete_superseded_review_runs",
        "final_handling_method": "delete",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": len(run_rows),
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_byte_count"],
        "skipped_count": 0 if apply else len(run_rows),
        "mutation_performed": bool(deleted_rows),
    }


def _compact_post_replay_attribution_runs(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    retain_recent_count: int,
    include_hashes: bool,
) -> dict[str, Any]:
    artifact_root = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_attribution_runs"
    runs = _run_dirs(artifact_root)
    retained = {path for path in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    deleted_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    candidate_count = 0
    for run in runs:
        receipt = _read_json_object(run / "post_replay_residual_event_governance_receipt.json") or {}
        runtime_sidecar_files = [
            path for path in sorted(run.iterdir()) if path.is_file() and path.name in ATTRIBUTION_RUNTIME_SIDECAR_FILE_NAMES
        ]
        if run not in retained:
            candidate_count += len(runtime_sidecar_files)
        run_rows.append(
            {
                "run_id": run.name,
                "run_ref": _relative_path(root, run),
                "status": receipt.get("status") or receipt.get("decision_status"),
                "runtime_sidecar_file_count": len(runtime_sidecar_files),
                "runtime_sidecar_byte_count": sum(path.stat().st_size for path in runtime_sidecar_files),
                "event_interpretations_preserved": (run / "event_interpretations.jsonl").exists(),
                "retained_full_runtime_sidecars": run in retained,
            }
        )
        if apply and run not in retained:
            for path in runtime_sidecar_files:
                deleted_rows.append(_delete_file(path, root=root, include_hash=include_hashes))
    compact = {
        "contract_type": "storage_post_replay_attribution_compact_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "run_count": len(runs),
        "recent_full_run_retention_count": retain_recent_count,
        "run_summaries": run_rows,
        "preserved_event_interpretation_file_name": "event_interpretations.jsonl",
        "deleted_runtime_sidecar_file_count": len(deleted_rows),
        "deleted_runtime_sidecar_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "post_replay_attribution_compact_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_rolling_retention",
        "final_handling_method": "rolling_retention",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": candidate_count,
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_runtime_sidecar_byte_count"],
        "skipped_count": 0,
        "mutation_performed": bool(deleted_rows),
    }


def _compact_failure_triage_runs(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    include_hashes: bool,
) -> dict[str, Any]:
    artifact_root = root / "storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_failure_triage_runs"
    runs = _run_dirs(artifact_root)
    compressed_rows: list[dict[str, Any]] = []
    skipped_count = 0
    run_rows: list[dict[str, Any]] = []
    candidate_count = 0
    for run in runs:
        receipt = _read_json_object(run / "post_replay_failure_triage_receipt.json") or {}
        row_file = run / "failure_triage_rows.jsonl"
        if row_file.exists():
            candidate_count += 1
        row = {
            "run_id": run.name,
            "run_ref": _relative_path(root, run),
            "status": receipt.get("status") or receipt.get("decision_status"),
            "row_file_ref": _relative_path(root, row_file) if row_file.exists() else None,
            "row_file_bytes": row_file.stat().st_size if row_file.exists() else 0,
        }
        if apply and row_file.exists():
            compressed_rows.append(_compress_file(row_file, root=root, include_hash=include_hashes))
        elif row_file.exists():
            skipped_count += 1
        run_rows.append(row)
    compact = {
        "contract_type": "storage_post_replay_failure_triage_compact_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "run_count": len(runs),
        "run_summaries": run_rows,
        "compressed_file_count": len(compressed_rows),
        "compressed_source_byte_count": sum(int(row["source"].get("byte_count") or 0) for row in compressed_rows),
        "mutation_performed": bool(compressed_rows),
    }
    output_path = output_root / "post_replay_failure_triage_compact_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_compress",
        "final_handling_method": "compress",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": candidate_count,
        "mutated_count": len(compressed_rows),
        "mutated_byte_count": compact["compressed_source_byte_count"],
        "skipped_count": skipped_count,
        "mutation_performed": bool(compressed_rows),
    }


def _compact_recent_refresh_runs(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    retain_recent_count: int,
) -> dict[str, Any]:
    artifact_root = root / "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/_manifests/recent_refresh_runs"
    runs = _run_dirs(artifact_root)
    retained = {path for path in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    deleted_rows: list[dict[str, Any]] = []
    for run in runs:
        if apply and run not in retained:
            deleted_rows.append(_delete_tree(run, root=root))
    compact = {
        "contract_type": "storage_te_recent_refresh_compact_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "run_count": len(runs),
        "recent_full_run_retention_count": retain_recent_count,
        "latest_run_refs": [_relative_path(root, path) for path in runs[-retain_recent_count:]],
        "deleted_run_count": len(deleted_rows),
        "deleted_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "te_recent_refresh_compact_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_rolling_retention",
        "final_handling_method": "rolling_retention",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": max(len(runs) - retain_recent_count, 0),
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_byte_count"],
        "skipped_count": 0,
        "mutation_performed": bool(deleted_rows),
    }


def _compact_te_monthly_run_side_products(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    retain_recent_count: int,
    include_hashes: bool,
) -> dict[str, Any]:
    artifact_root = root / TE_MONTHLY_SOURCE_ROOT
    runs = _te_monthly_run_dirs(artifact_root)
    retained = {path for path in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    deleted_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    candidate_count = 0
    source_file_names = {
        "saved/trading_economics_calendar_event.csv",
        "cleaned/trading_economics_calendar_event.jsonl",
        "cleaned/schema.json",
    }
    for run in runs:
        side_products = [run / name for name in sorted(TE_RUN_SIDE_PRODUCT_FILE_NAMES) if (run / name).is_file()]
        source_files = [run / name for name in sorted(source_file_names) if (run / name).is_file()]
        if run not in retained:
            candidate_count += len(side_products)
        receipt = _read_json_object(run / "completion_receipt.json") or {}
        row_counts: Mapping[str, Any] = {}
        if isinstance(receipt.get("row_counts"), Mapping):
            row_counts = dict(receipt["row_counts"])
        elif isinstance(receipt.get("runs"), list):
            for item in receipt["runs"]:
                if isinstance(item, Mapping) and isinstance(item.get("row_counts"), Mapping):
                    row_counts = dict(item["row_counts"])
                    break
        run_rows.append(
            {
                "month": run.parent.parent.name,
                "run_id": run.name,
                "run_ref": _relative_path(root, run),
                "status": receipt.get("status"),
                "started_at": receipt.get("started_at"),
                "completed_at": receipt.get("completed_at"),
                "row_counts": row_counts,
                "source_payload_refs": [_relative_path(root, path) for path in source_files],
                "source_payload_byte_count": sum(path.stat().st_size for path in source_files),
                "side_product_refs": [_relative_path(root, path) for path in side_products],
                "side_product_byte_count": sum(path.stat().st_size for path in side_products),
                "retained_full_side_products": run in retained,
            }
        )
        if apply and run not in retained:
            for path in side_products:
                deleted_rows.append(_delete_file(path, root=root, include_hash=include_hashes))
    compact = {
        "contract_type": "storage_te_monthly_source_provenance_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "run_count": len(runs),
        "recent_full_run_side_product_retention_count": retain_recent_count,
        "latest_run_refs": [_relative_path(root, path) for path in runs[-retain_recent_count:]],
        "run_summaries": run_rows,
        "deleted_side_product_file_count": len(deleted_rows),
        "deleted_side_product_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "source_payload_mutation_performed": False,
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "te_monthly_source_provenance_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_rolling_retention",
        "final_handling_method": "rolling_retention",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": candidate_count,
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_side_product_byte_count"],
        "skipped_count": max(candidate_count - len(deleted_rows), 0),
        "mutation_performed": bool(deleted_rows),
        "source_payload_mutation_performed": False,
    }


def _month_dir_saved_artifacts(month_dir: Path, filename: str) -> tuple[Path, ...]:
    candidates = sorted(month_dir.glob(f"runs/*/saved/{filename}"))
    candidates.extend(sorted(month_dir.glob(f"saved/{filename}")))
    return tuple(path for path in dict.fromkeys(candidates) if path.is_file() and not path.is_symlink())


def _receipt_has_success(receipt: Mapping[str, Any]) -> bool:
    if str(receipt.get("status") or "").lower() in COMPLETE_STATUSES:
        return True
    runs = receipt.get("runs")
    if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes)):
        return False
    return any(
        isinstance(run, Mapping) and str(run.get("status") or "").lower() in COMPLETE_STATUSES
        for run in runs
    )


def _receipt_row_counts(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(receipt.get("row_counts"), Mapping):
        return dict(receipt["row_counts"])
    runs = receipt.get("runs")
    if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes)):
        return {}
    row_counts: dict[str, int] = {}
    for run in runs:
        if not isinstance(run, Mapping) or str(run.get("status") or "").lower() not in COMPLETE_STATUSES:
            continue
        values = run.get("row_counts")
        if not isinstance(values, Mapping):
            continue
        for key, value in values.items():
            row_counts[str(key)] = row_counts.get(str(key), 0) + int(value or 0)
    return row_counts


def _event_feed_month_dirs(root: Path) -> tuple[tuple[str, Path], ...]:
    base = root / "storage/01_source_data/monthly_backfill"
    month_dirs: list[tuple[str, Path]] = []
    for source_id in sorted(EVENT_FEED_MONTHLY_SOURCE_ARTIFACTS):
        source_root = base / source_id
        if not source_root.exists():
            continue
        for month_dir in _run_dirs(source_root):
            if re.fullmatch(r"20\d{2}-\d{2}", month_dir.name):
                month_dirs.append((source_id, month_dir))
    return tuple(month_dirs)


def _compact_event_feed_monthly_completion_receipts(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    include_hashes: bool,
) -> dict[str, Any]:
    dashboard_active_refs = _proof_dashboard_active_input_refs(root)
    source_month_rows: list[dict[str, Any]] = []
    run_sidecar_rows: list[dict[str, Any]] = []
    deleted_rows: list[dict[str, Any]] = []
    candidate_count = 0
    skipped_count = 0
    for source_id, month_dir in _event_feed_month_dirs(root):
        receipt_path = month_dir / "completion_receipt.json"
        if receipt_path.is_file() and not receipt_path.is_symlink():
            receipt_ref = _relative_path(root, receipt_path)
            filename = EVENT_FEED_MONTHLY_SOURCE_ARTIFACTS[source_id]
            saved_artifacts = _month_dir_saved_artifacts(month_dir, filename)
            receipt = _read_json_object(receipt_path) or {}
            row_counts = _receipt_row_counts(receipt)
            eligible = (
                (bool(saved_artifacts) or bool(row_counts))
                and _receipt_has_success(receipt)
                and receipt_ref not in dashboard_active_refs
            )
            if eligible:
                candidate_count += 1
            else:
                skipped_count += 1
            source_month_rows.append(
                {
                    "source_id": source_id,
                    "month": month_dir.name,
                    "receipt_ref": receipt_ref,
                    "status": receipt.get("status"),
                    "row_counts": row_counts,
                    "saved_payload_refs": [_relative_path(root, path) for path in saved_artifacts],
                    "delete_eligible": eligible,
                    "skip_reason": None
                    if eligible
                    else (
                        "dashboard_active_input"
                        if receipt_ref in dashboard_active_refs
                        else "missing_saved_payload_or_row_counts"
                        if not saved_artifacts and not row_counts
                        else "receipt_not_succeeded"
                    ),
                }
            )
            if apply and eligible:
                deleted_rows.append(_delete_file(receipt_path, root=root, include_hash=include_hashes))
        if source_id not in EVENT_FEED_SQL_ONLY_RUN_SIDECAR_SOURCE_IDS:
            continue
        for run_dir in _run_dirs(month_dir / "runs"):
            run_receipt = _read_json_object(run_dir / "completion_receipt.json") or {}
            run_row_counts = _receipt_row_counts(run_receipt)
            run_sidecars = [
                run_dir / name
                for name in sorted(EVENT_FEED_RUN_SIDECAR_FILE_NAMES)
                if (run_dir / name).is_file() and not (run_dir / name).is_symlink()
            ]
            if not run_sidecars:
                continue
            active_sidecars = [
                path for path in run_sidecars if _relative_path(root, path) in dashboard_active_refs
            ]
            skipped_count += len(active_sidecars)
            deletable_sidecars = [path for path in run_sidecars if path not in active_sidecars]
            run_eligible = bool(deletable_sidecars) and _receipt_has_success(run_receipt) and bool(run_row_counts)
            if run_eligible:
                candidate_count += len(deletable_sidecars)
            else:
                skipped_count += len(run_sidecars)
            run_sidecar_rows.append(
                {
                    "source_id": source_id,
                    "month": month_dir.name,
                    "run_id": run_dir.name,
                    "run_ref": _relative_path(root, run_dir),
                    "status": run_receipt.get("status"),
                    "row_counts": run_row_counts,
                    "sidecar_refs": [_relative_path(root, path) for path in run_sidecars],
                    "active_sidecar_refs": [_relative_path(root, path) for path in active_sidecars],
                    "delete_eligible": run_eligible,
                    "skip_reason": None
                    if run_eligible
                    else (
                        "dashboard_active_input"
                        if active_sidecars
                        else "missing_row_counts"
                        if not run_row_counts
                        else "receipt_not_succeeded"
                    ),
                }
            )
            if apply and run_eligible:
                for path in deletable_sidecars:
                    deleted_rows.append(_delete_file(path, root=root, include_hash=include_hashes))
    compact = {
        "contract_type": "storage_event_feed_monthly_receipt_compaction_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": EVENT_FEED_MONTHLY_RECEIPT_ACTION_REF,
        "source_ids": sorted(EVENT_FEED_MONTHLY_SOURCE_ARTIFACTS),
        "source_month_count": len(source_month_rows),
        "source_month_summaries": source_month_rows,
        "run_sidecar_count": len(run_sidecar_rows),
        "run_sidecar_summaries": run_sidecar_rows,
        "deleted_receipt_count": len(deleted_rows),
        "deleted_receipt_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "deleted_sidecar_file_count": len(deleted_rows),
        "deleted_sidecar_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "source_payload_mutation_performed": False,
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "event_feed_monthly_receipt_compaction_manifest.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": EVENT_FEED_MONTHLY_RECEIPT_ACTION_REF,
        "action": "compact_then_delete_redundant_monthly_receipts",
        "final_handling_method": "delete",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": candidate_count,
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_receipt_byte_count"],
        "skipped_count": skipped_count,
        "mutation_performed": bool(deleted_rows),
        "source_payload_mutation_performed": False,
    }


def _realtime_loop_has_exception(receipt: Mapping[str, Any] | None) -> bool:
    if not receipt:
        return True
    if str(receipt.get("loop_status") or "").lower() not in {"completed", "succeeded", "success"}:
        return True
    failed = receipt.get("failed_cycle_indexes")
    if isinstance(failed, Sequence) and not isinstance(failed, (str, bytes)) and len(failed) > 0:
        return True
    if receipt.get("broker_calls_performed") or receipt.get("account_mutation_performed") or receipt.get("model_activation_performed"):
        return True
    return False


def _compact_realtime_monitor(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    apply: bool,
    retain_recent_count: int,
) -> dict[str, Any]:
    artifact_root = root / "storage/04_execution_artifacts/runtime/realtime_monitor"
    runs = _run_dirs(artifact_root)
    retained = {path for path in runs[-retain_recent_count:]} if retain_recent_count > 0 else set()
    deleted_rows: list[dict[str, Any]] = []
    exception_count = 0
    status_counts: dict[str, int] = {}
    for run in runs:
        receipt = _read_json_object(run / "loop_receipt.json")
        status = str((receipt or {}).get("loop_status") or "missing")
        status_counts[status] = status_counts.get(status, 0) + 1
        has_exception = _realtime_loop_has_exception(receipt)
        if has_exception:
            exception_count += 1
        if apply and run not in retained and not has_exception:
            deleted_rows.append(_delete_tree(run, root=root))
    compact = {
        "contract_type": "storage_realtime_monitor_rolling_summary",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": _relative_path(root, artifact_root),
        "loop_count": len(runs),
        "status_counts": dict(sorted(status_counts.items())),
        "exception_loop_count": exception_count,
        "recent_full_loop_retention_count": retain_recent_count,
        "latest_loop_refs": [_relative_path(root, path) for path in runs[-retain_recent_count:]],
        "deleted_loop_count": len(deleted_rows),
        "deleted_byte_count": sum(int(row.get("byte_count") or 0) for row in deleted_rows),
        "mutation_performed": bool(deleted_rows),
    }
    output_path = output_root / "realtime_monitor_rolling_summary.json"
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": _relative_path(root, artifact_root),
        "action": "compact_then_rolling_retention",
        "final_handling_method": "rolling_retention",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": max(len(runs) - retain_recent_count - exception_count, 0),
        "mutated_count": len(deleted_rows),
        "mutated_byte_count": compact["deleted_byte_count"],
        "skipped_count": exception_count,
        "mutation_performed": bool(deleted_rows),
    }


def _compact_task_keys(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    artifact_ref: str,
    apply: bool,
) -> dict[str, Any]:
    artifact_root = root / artifact_ref
    task_keys = sorted(artifact_root.rglob("task_key.json")) if artifact_root.exists() else []
    by_source: dict[str, int] = {}
    by_month: dict[str, int] = {}
    missing_status_count = 0
    for path in task_keys:
        payload = _read_json_object(path) or {}
        source = str(payload.get("source") or path.parent.parent.name if len(path.parts) >= 2 else "unknown")
        by_source[source] = by_source.get(source, 0) + 1
        controls = payload.get("manager_controls") if isinstance(payload.get("manager_controls"), Mapping) else {}
        month = str(controls.get("start_month") or path.parent.parent.name if len(path.parts) >= 2 else "unknown")
        by_month[month] = by_month.get(month, 0) + 1
        if not any(payload.get(key) for key in ("status", "task_status", "request_status", "stage_status", "result_status")):
            missing_status_count += 1
    compact = {
        "contract_type": "storage_task_key_compact_manifest",
        "generated_at_utc": generated_at_utc,
        "artifact_ref": artifact_ref,
        "task_key_count": len(task_keys),
        "missing_status_count": missing_status_count,
        "by_source": dict(sorted(by_source.items())),
        "by_month": dict(sorted(by_month.items())),
        "delete_performed": False,
        "delete_blocker": "task_key_status_missing" if missing_status_count else None,
    }
    output_path = output_root / (artifact_ref.replace("/", "__") + "_task_key_compact_manifest.json")
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": artifact_ref,
        "action": "compact_delete_blocked",
        "final_handling_method": "delete",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": len(task_keys),
        "mutated_count": 0,
        "mutated_byte_count": 0,
        "skipped_count": len(task_keys),
        "mutation_performed": False,
        "blocker": "task_key_status_missing",
    }


def _compact_jsonl_rollup(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    artifact_ref: str,
    contract_type: str,
    output_name: str,
    apply: bool,
) -> dict[str, Any]:
    artifact_path = root / artifact_ref
    line_count = 0
    first_line: str | None = None
    last_line: str | None = None
    if artifact_path.exists():
        with artifact_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    first_line = first_line or stripped[:500]
                    last_line = stripped[:500]
                    line_count += 1
    compact = {
        "contract_type": contract_type,
        "generated_at_utc": generated_at_utc,
        "artifact_ref": artifact_ref,
        "line_count": line_count,
        "byte_count": artifact_path.stat().st_size if artifact_path.exists() else 0,
        "first_line_preview": first_line,
        "last_line_preview": last_line,
        "mutation_performed": False,
    }
    output_path = output_root / output_name
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": artifact_ref,
        "action": "compact_rollup_only",
        "final_handling_method": "rolling_retention",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": 1 if artifact_path.exists() else 0,
        "mutated_count": 0,
        "mutated_byte_count": 0,
        "skipped_count": 1 if artifact_path.exists() else 0,
        "mutation_performed": False,
        "blocker": "append_only_log_not_segmented",
    }


def _compact_snapshot_dir(
    *,
    root: Path,
    output_root: Path,
    generated_at_utc: str,
    artifact_ref: str,
    contract_type: str,
    output_name: str,
    apply: bool,
) -> dict[str, Any]:
    artifact_root = root / artifact_ref
    inventory = _path_inventory(artifact_root)
    compact = {
        "contract_type": contract_type,
        "generated_at_utc": generated_at_utc,
        "artifact_ref": artifact_ref,
        **inventory,
        "mutation_performed": False,
    }
    output_path = output_root / output_name
    if apply:
        _write_json_object(output_path, compact)
    return {
        "contract_type": "storage_lifecycle_gap_action_receipt",
        "artifact_ref": artifact_ref,
        "action": "compact_rollup_only",
        "final_handling_method": "rolling_retention",
        "compact_ref": _relative_path(root, output_path),
        "candidate_count": int(inventory.get("file_count") or 0),
        "mutated_count": 0,
        "mutated_byte_count": 0,
        "skipped_count": int(inventory.get("file_count") or 0),
        "mutation_performed": False,
        "blocker": "snapshot_latest_pointer_not_verified",
    }


def execute_lifecycle_gap_actions(
    *,
    root: Path,
    output_root: Path = DEFAULT_COMPACT_OUTPUT_ROOT,
    apply: bool = False,
    generated_at_utc: str | None = None,
    action_refs: Sequence[str] | None = None,
    retain_recent_replay_runs: int = 3,
    retain_recent_attribution_runs: int = 3,
    retain_recent_te_refresh_runs: int = 24,
    retain_recent_te_monthly_runs: int = 24,
    retain_recent_realtime_loops: int = 100,
    include_hashes: bool = False,
) -> tuple[dict[str, Any], ...]:
    generated = generated_at_utc or _now_utc()
    resolved_output_root = _resolve(root.resolve(), output_root)
    enabled_refs = set(action_refs or ())

    def enabled(artifact_ref: str) -> bool:
        return not enabled_refs or artifact_ref in enabled_refs

    receipts: list[dict[str, Any]] = []
    if enabled("storage/05_replay_datasets/promotion_replay_candidate_policy/replay_execution_runs"):
        receipts.append(
        _compact_replay_execution_runs(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            retain_recent_count=retain_recent_replay_runs,
            include_hashes=include_hashes,
        ))
    if enabled("storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_attribution_runs"):
        receipts.append(
        _compact_post_replay_attribution_runs(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            retain_recent_count=retain_recent_attribution_runs,
            include_hashes=include_hashes,
        ))
    if enabled("storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_review_runs"):
        receipts.append(
        _compact_post_replay_review_runs(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
        ))
    if enabled("storage/05_replay_datasets/promotion_replay_candidate_policy/post_replay_failure_triage_runs"):
        receipts.append(
        _compact_failure_triage_runs(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            include_hashes=include_hashes,
        ))
    if enabled("storage/01_source_data/monthly_backfill/trading_economics_calendar_web/_manifests/recent_refresh_runs"):
        receipts.append(
        _compact_recent_refresh_runs(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            retain_recent_count=retain_recent_te_refresh_runs,
        ))
    if enabled(TE_MONTHLY_SOURCE_ROOT.as_posix()):
        receipts.append(
        _compact_te_monthly_run_side_products(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            retain_recent_count=retain_recent_te_monthly_runs,
            include_hashes=include_hashes,
        ))
    if enabled(EVENT_FEED_MONTHLY_RECEIPT_ACTION_REF):
        receipts.append(
        _compact_event_feed_monthly_completion_receipts(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            include_hashes=include_hashes,
        ))
    if enabled("storage/04_execution_artifacts/runtime/realtime_monitor"):
        receipts.append(
        _compact_realtime_monitor(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            apply=apply,
            retain_recent_count=retain_recent_realtime_loops,
        ))
    if enabled("storage/02_control_plane/runtime/model_05_option_expression"):
        receipts.append(
        _compact_task_keys(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            artifact_ref="storage/02_control_plane/runtime/model_05_option_expression",
            apply=apply,
        ))
    if enabled("storage/02_control_plane/runtime/provider_task_keys"):
        receipts.append(
        _compact_task_keys(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            artifact_ref="storage/02_control_plane/runtime/provider_task_keys",
            apply=apply,
        ))
    if enabled("storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl"):
        receipts.append(
        _compact_jsonl_rollup(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            artifact_ref="storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl",
            contract_type="storage_scheduler_decision_rollup_summary",
            output_name="historical_scheduler_decisions_rollup_summary.json",
            apply=apply,
        ))
    if enabled("storage/02_control_plane/runtime/stage_coverage"):
        receipts.append(
        _compact_snapshot_dir(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            artifact_ref="storage/02_control_plane/runtime/stage_coverage",
            contract_type="storage_stage_coverage_rollup_summary",
            output_name="stage_coverage_rollup_summary.json",
            apply=apply,
        ))
    if enabled("storage/02_control_plane/runtime/stage_run_dashboard"):
        receipts.append(
        _compact_snapshot_dir(
            root=root,
            output_root=resolved_output_root,
            generated_at_utc=generated,
            artifact_ref="storage/02_control_plane/runtime/stage_run_dashboard",
            contract_type="storage_stage_run_dashboard_rollup_summary",
            output_name="stage_run_dashboard_rollup_summary.json",
            apply=apply,
        ))
    return tuple(receipts)


def _lifecycle_gap_action_summary(receipts: Sequence[Mapping[str, Any]], *, apply: bool) -> dict[str, Any]:
    return {
        "contract_type": "storage_lifecycle_gap_action_summary",
        "apply": apply,
        "receipt_count": len(receipts),
        "mutation_performed": any(bool(row.get("mutation_performed")) for row in receipts),
        "mutated_count": sum(int(row.get("mutated_count") or 0) for row in receipts),
        "mutated_byte_count": sum(int(row.get("mutated_byte_count") or 0) for row in receipts),
        "skipped_count": sum(int(row.get("skipped_count") or 0) for row in receipts),
        "by_final_handling_method": {
            method: sum(1 for row in receipts if row.get("final_handling_method") == method)
            for method in ("delete", "compress", "rolling_retention")
        },
    }


def _state_months(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    prefix = "model_training_fold_state_"
    if not stem.startswith(prefix):
        return None
    body = stem.removeprefix(prefix)
    parts = body.split("_")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _safe_target_token(value: Any) -> str:
    token = "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())
    return token or "unknown"


def _fold_id(target_symbol: str, start_month: str) -> str:
    return f"fold_{_safe_target_token(target_symbol)}_{start_month[:4]}"


def _payload_target_symbol(payload: Mapping[str, Any]) -> str:
    target_symbol = payload.get("target_symbol") or payload.get("selected_target_symbol")
    if target_symbol:
        return str(target_symbol)
    target_refs = payload.get("target_refs") or payload.get("pre_replay_target_refs")
    if isinstance(target_refs, Sequence) and not isinstance(target_refs, (str, bytes)) and target_refs:
        return str(target_refs[0])
    return "AAPL"


def _stage_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    stages = payload.get("stages")
    if not isinstance(stages, list):
        return []
    return [dict(stage) for stage in stages if isinstance(stage, Mapping)]


def _is_completed_model_worker_fold(payload: Mapping[str, Any]) -> bool:
    stages = _stage_rows(payload)
    if not stages:
        return False
    model_stages = [stage for stage in stages if str(stage.get("stage_type") or "") in MODEL_WORKER_STAGE_TYPES]
    if not model_stages:
        return False
    layer_stage_types: dict[int, set[str]] = {}
    for stage in model_stages:
        try:
            layer = int(stage.get("layer") or 0)
        except (TypeError, ValueError):
            return False
        if str(stage.get("status") or "") not in COMPLETE_STATUSES:
            return False
        layer_stage_types.setdefault(layer, set()).add(str(stage.get("stage_type") or ""))
    expected_layers = set(range(1, 11))
    return set(layer_stage_types) == expected_layers and all(
        stage_types >= MODEL_WORKER_STAGE_TYPES for stage_types in layer_stage_types.values()
    )


def _backup_candidate(*, fold_id: str, start_month: str, end_month: str, state_path: Path) -> dict[str, Any]:
    output_path = f"storage/sql_backups/folds/{fold_id}/pending/trading_database.dump"
    return {
        "contract_type": "storage_fold_sql_backup_candidate",
        "fold_id": fold_id,
        "start_month": start_month,
        "end_month": end_month,
        "manager_fold_state_path": str(state_path),
        "backup_mode": "logical_pg_dump_custom",
        "output_path": output_path,
        "backup_command_template": [
            "pg_dump",
            "-Fc",
            "--no-owner",
            "--no-acl",
            "--file",
            output_path,
            "$DATABASE_URL",
        ],
        "globals_backup_command_template": [
            "pg_dumpall",
            "--globals-only",
            "--file",
            output_path.removesuffix(".dump") + ".globals.sql",
        ],
        "restore_smoke_required": True,
        "checksum_required": True,
        "source_delete_allowed_before_backup": False,
    }


def _fold_source_cleanup_candidate(*, fold_id: str, source_folder: Path, root: Path) -> dict[str, Any]:
    relative = source_folder.relative_to(root).as_posix()
    file_count = 0
    byte_count = 0
    for path in source_folder.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        file_count += 1
        try:
            byte_count += path.stat().st_size
        except OSError:
            pass
    return {
        "contract_type": "storage_fold_source_cleanup_candidate",
        "fold_id": fold_id,
        "source_folder_path": relative,
        "cleanup_unit": "fold_folder",
        "retention_boundary": "fold_complete_delete_allowed",
        "file_count": file_count,
        "byte_count": byte_count,
        "required_completion_gate": "fold_layers_01_10_model_evaluation_complete",
        "requires_artifact_index": True,
        "requires_protected_set_clear": True,
        "requires_quarantine_recheck": True,
        "requires_deletion_receipt": True,
        "preserve_reusable_m01_m02_source_data": True,
        "deletion_performed": False,
    }


def detect_completed_model_worker_folds(*, manager_root: Path) -> tuple[dict[str, Any], ...]:
    runtime_root = manager_root / "storage" / "runtime"
    if not runtime_root.exists():
        return ()
    candidates: list[dict[str, Any]] = []
    for path in sorted(runtime_root.glob(FOLD_STATE_GLOB)):
        months = _state_months(path)
        if months is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping) or not _is_completed_model_worker_fold(payload):
            continue
        start_month = str(payload.get("start_month") or months[0])
        end_month = str(payload.get("end_month") or months[1])
        target_symbol = _payload_target_symbol(payload)
        candidates.append(
            _backup_candidate(
                fold_id=_fold_id(target_symbol, start_month),
                start_month=start_month,
                end_month=end_month,
                state_path=path,
            )
        )
    return tuple(candidates)


def detect_fold_scoped_source_cleanup_candidates(
    *,
    root: Path,
    completed_fold_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Find fold-folder source cleanup candidates without mutating storage."""

    source_root = root / FOLD_SCOPED_SOURCE_ROOT
    if not source_root.exists():
        return ()
    completed = set(completed_fold_ids)
    candidates: list[dict[str, Any]] = []
    for folder in sorted(source_root.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name not in completed:
            continue
        candidates.append(_fold_source_cleanup_candidate(fold_id=folder.name, source_folder=folder, root=root))
    return tuple(candidates)


def run_storage_maintenance(
    *,
    root: Path = Path("."),
    archive_root: Path = Path("storage/90_lifecycle/archive"),
    compact_output_root: Path = DEFAULT_COMPACT_OUTPUT_ROOT,
    manager_root: Path | None = None,
    apply_local_retention: bool = False,
    apply_lifecycle_gap_actions: bool = False,
    include_local_retention: bool = True,
    include_fold_monitor: bool = True,
    include_proof_sidecar_audit: bool = True,
    include_hashes: bool = False,
    retain_recent_replay_runs: int = 3,
    retain_recent_attribution_runs: int = 3,
    retain_recent_te_refresh_runs: int = 24,
    retain_recent_te_monthly_runs: int = 24,
    retain_recent_realtime_loops: int = 100,
    lifecycle_gap_action_refs: Sequence[str] | None = None,
    generated_at_utc: str | None = None,
) -> StorageMaintenanceSummary:
    root = root.resolve()
    generated = generated_at_utc or _now_utc()
    storage_root_inventory = _build_storage_root_inventory(root)
    local_retention_summary = {"archive": 0, "delete": 0, "retain": 0, "skip": 0}
    if include_local_retention:
        retention = plan_retention(root=root, archive_root=archive_root, dry_run=not apply_local_retention)
        if apply_local_retention:
            retention = apply_retention_plan(retention)
        local_retention_summary = retention.summary
    resolved_manager_root = manager_root.resolve() if manager_root is not None else None
    fold_candidates = (
        detect_completed_model_worker_folds(manager_root=resolved_manager_root)
        if include_fold_monitor and resolved_manager_root is not None
        else ()
    )
    completed_fold_ids = tuple(str(candidate["fold_id"]) for candidate in fold_candidates)
    fold_source_cleanup_candidates = detect_fold_scoped_source_cleanup_candidates(
        root=root,
        completed_fold_ids=completed_fold_ids,
    )
    lifecycle_gap_findings = detect_lifecycle_gap_findings(root=root)
    if include_proof_sidecar_audit:
        proof_sidecar_audit_summary, proof_sidecar_audit_findings = audit_proof_sidecars(root=root)
    else:
        proof_sidecar_audit_summary = _empty_proof_sidecar_audit_summary(skipped=True)
        proof_sidecar_audit_findings = ()
    lifecycle_gap_action_receipts = execute_lifecycle_gap_actions(
        root=root,
        output_root=compact_output_root,
        apply=apply_lifecycle_gap_actions,
        generated_at_utc=generated,
        action_refs=lifecycle_gap_action_refs,
        retain_recent_replay_runs=retain_recent_replay_runs,
        retain_recent_attribution_runs=retain_recent_attribution_runs,
        retain_recent_te_refresh_runs=retain_recent_te_refresh_runs,
        retain_recent_te_monthly_runs=retain_recent_te_monthly_runs,
        retain_recent_realtime_loops=retain_recent_realtime_loops,
        include_hashes=include_hashes,
    )
    fold_source_cleanup_phase = (
        "ready_for_quarantine_review" if fold_source_cleanup_candidates else "no_fold_scoped_source_cleanup_candidates"
    )
    if not include_fold_monitor:
        fold_source_cleanup_phase = "fold_monitor_skipped"
    return StorageMaintenanceSummary(
        contract_type="storage_scheduled_maintenance_summary",
        generated_at_utc=generated,
        root=str(root),
        local_retention_enabled=include_local_retention,
        local_retention_apply=apply_local_retention,
        local_retention_summary=local_retention_summary,
        storage_root_inventory_summary=_storage_root_inventory_summary(storage_root_inventory),
        storage_root_inventory=storage_root_inventory,
        manager_root=str(resolved_manager_root) if resolved_manager_root is not None else None,
        fold_monitor_enabled=include_fold_monitor and resolved_manager_root is not None,
        completed_fold_count=len(fold_candidates),
        completed_fold_ids=completed_fold_ids,
        fold_backup_candidates=fold_candidates,
        fold_source_cleanup_candidates=fold_source_cleanup_candidates,
        fold_source_cleanup_candidate_count=len(fold_source_cleanup_candidates),
        lifecycle_gap_audit_summary=_lifecycle_gap_audit_summary(lifecycle_gap_findings),
        lifecycle_gap_findings=lifecycle_gap_findings,
        lifecycle_gap_action_summary=_lifecycle_gap_action_summary(
            lifecycle_gap_action_receipts,
            apply=apply_lifecycle_gap_actions,
        ),
        lifecycle_gap_action_receipts=lifecycle_gap_action_receipts,
        proof_sidecar_audit_summary=proof_sidecar_audit_summary,
        proof_sidecar_audit_findings=proof_sidecar_audit_findings,
        fold_sql_backup_phase_status="ready_for_storage_backup" if fold_candidates else "no_completed_fold_detected",
        fold_source_cleanup_phase_status=fold_source_cleanup_phase,
        deletion_phase_status="local_retention_only" if include_local_retention else "local_retention_skipped",
        provider_calls_performed=False,
        model_activation_performed=False,
        broker_execution_performed=False,
        account_mutation_performed=False,
    )


def write_storage_maintenance_summary(summary: StorageMaintenanceSummary, *, output_path: Path, root: Path) -> None:
    destination = _resolve(root.resolve(), output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(summary.to_json(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the storage-owned scheduled maintenance pass.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root. Defaults to current directory.")
    parser.add_argument("--archive-root", type=Path, default=Path("storage/90_lifecycle/archive"))
    parser.add_argument("--compact-output-root", type=Path, default=DEFAULT_COMPACT_OUTPUT_ROOT)
    parser.add_argument("--manager-root", type=Path, help="Manager repository root for fold-state monitoring.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MAINTENANCE_OUTPUT)
    parser.add_argument("--apply-local-retention", action="store_true", help="Archive/delete eligible local runtime files.")
    parser.add_argument(
        "--apply-lifecycle-gap-actions",
        action="store_true",
        help="Write compact contracts and apply explicit state-triggered lifecycle gap actions.",
    )
    parser.add_argument(
        "--lifecycle-gap-action-ref",
        action="append",
        default=[],
        help="Limit lifecycle gap action execution to an exact artifact_ref. Repeat for multiple refs.",
    )
    parser.add_argument("--include-hashes", action="store_true", help="Hash mutated source artifacts in action receipts.")
    parser.add_argument("--retain-recent-replay-runs", type=int, default=3)
    parser.add_argument("--retain-recent-attribution-runs", type=int, default=3)
    parser.add_argument("--retain-recent-te-refresh-runs", type=int, default=24)
    parser.add_argument("--retain-recent-te-monthly-runs", type=int, default=24)
    parser.add_argument("--retain-recent-realtime-loops", type=int, default=100)
    parser.add_argument("--skip-local-retention", action="store_true", help="Skip local retention planning.")
    parser.add_argument("--skip-fold-monitor", action="store_true", help="Skip direct manager fold-state reads.")
    parser.add_argument(
        "--skip-proof-sidecar-audit",
        action="store_true",
        help="Skip the proof/sidecar bucket audit for fast heartbeat-style maintenance checks.",
    )
    parser.add_argument("--json", action="store_true", help="Print the summary JSON to stdout.")
    args = parser.parse_args(argv)
    summary = run_storage_maintenance(
        root=args.root,
        archive_root=args.archive_root,
        compact_output_root=args.compact_output_root,
        manager_root=args.manager_root,
        apply_local_retention=args.apply_local_retention,
        apply_lifecycle_gap_actions=args.apply_lifecycle_gap_actions,
        include_local_retention=not args.skip_local_retention,
        include_fold_monitor=not args.skip_fold_monitor,
        include_proof_sidecar_audit=not args.skip_proof_sidecar_audit,
        include_hashes=args.include_hashes,
        retain_recent_replay_runs=args.retain_recent_replay_runs,
        retain_recent_attribution_runs=args.retain_recent_attribution_runs,
        retain_recent_te_refresh_runs=args.retain_recent_te_refresh_runs,
        retain_recent_te_monthly_runs=args.retain_recent_te_monthly_runs,
        retain_recent_realtime_loops=args.retain_recent_realtime_loops,
        lifecycle_gap_action_refs=args.lifecycle_gap_action_ref or None,
    )
    write_storage_maintenance_summary(summary, output_path=args.output_path, root=args.root)
    if args.json:
        print(summary.to_json(), end="")
    return 0


__all__ = [
    "DEFAULT_MAINTENANCE_OUTPUT",
    "DEFAULT_COMPACT_OUTPUT_ROOT",
    "StorageMaintenanceSummary",
    "audit_proof_sidecars",
    "detect_completed_model_worker_folds",
    "detect_fold_scoped_source_cleanup_candidates",
    "detect_lifecycle_gap_findings",
    "execute_lifecycle_gap_actions",
    "run_storage_maintenance",
    "write_storage_maintenance_summary",
]
