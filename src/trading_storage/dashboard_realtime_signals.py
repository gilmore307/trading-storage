"""Realtime signal dashboard read-model producer.

This producer summarizes execution-owned realtime/shadow monitoring evidence
from storage artifacts. It is deliberately read-only: it does not start realtime
monitoring, call providers, activate models, build orders, or mutate accounts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from .artifact_store import now_utc
from .dashboard_read_models import materialize_dashboard_read_model

REALTIME_SIGNAL_SUMMARY_CONTRACT = "realtime_signal_summary"
REALTIME_SIGNAL_SUMMARY_SCHEMA_REF = f"storage/dashboard_cache/schemas/{REALTIME_SIGNAL_SUMMARY_CONTRACT}.schema.json"


def _default_storage_root() -> Path:
    explicit = os.environ.get("TRADING_STORAGE_FILES_ROOT")
    if explicit:
        return Path(explicit)
    root = Path(os.environ.get("TRADING_STORAGE_ROOT", "/root/projects/trading-storage"))
    return root if root.name == "storage" else root / "storage"


DEFAULT_STORAGE_ROOT = _default_storage_root()
DEFAULT_EXECUTION_STORAGE_ROOT = Path(os.environ.get("TRADING_EXECUTION_STORAGE_ROOT", str(DEFAULT_STORAGE_ROOT / "execution_artifacts")))
DEFAULT_TRADING_EXECUTION_ROOT = DEFAULT_EXECUTION_STORAGE_ROOT
DEFAULT_STALE_AFTER_SECONDS = 30

MONITOR_RECEIPT_PATTERNS = (
    "runtime/realtime_monitor/**/*.json",
    "realtime_monitor/**/*.json",
    "**/loop_receipt.json",
)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _latest_monitor_receipt(*, execution_root: Path) -> tuple[Path, dict[str, Any]] | None:
    candidates: list[Path] = []
    for pattern in MONITOR_RECEIPT_PATTERNS:
        try:
            candidates.extend(path for path in execution_root.glob(pattern) if path.is_file())
        except OSError:
            continue
    candidates = sorted(set(candidates), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        payload = _load_json(path)
        if not payload:
            continue
        contract_type = str(payload.get("contract_type") or "")
        if contract_type in {
            "execution_realtime_monitor_loop_receipt",
            "execution_realtime_monitor_smoke_receipt",
            "execution_realtime_monitor_failed_cycle_receipt",
        } or "cycle_summary" in payload or "summary" in payload:
            return path, payload
    return None


def _latest_updated_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return None


def _age_seconds(path: Path) -> int | None:
    try:
        return int(max(0, time.time() - path.stat().st_mtime))
    except OSError:
        return None


def _summary_from_receipt(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = receipt.get("summary")
    if isinstance(summary, Mapping):
        return summary
    cycle_summary = receipt.get("cycle_summary")
    if isinstance(cycle_summary, Mapping) and isinstance(cycle_summary.get("summary"), Mapping):
        return cycle_summary["summary"]
    cycle_summaries = receipt.get("cycle_summaries")
    if isinstance(cycle_summaries, list) and cycle_summaries:
        last = cycle_summaries[-1]
        if isinstance(last, Mapping) and isinstance(last.get("summary"), Mapping):
            return last["summary"]
    return {}


def _cycle_counts(receipt: Mapping[str, Any]) -> tuple[int, int]:
    cycle_summaries = receipt.get("cycle_summaries")
    if isinstance(cycle_summaries, list):
        failed = sum(1 for row in cycle_summaries if isinstance(row, Mapping) and row.get("cycle_status") != "succeeded")
        return len(cycle_summaries), failed
    cycle_summary = receipt.get("cycle_summary")
    if isinstance(cycle_summary, Mapping):
        return 1, 0 if cycle_summary.get("cycle_status") == "succeeded" else 1
    return (1, 0) if receipt else (0, 0)


def _truthy(value: object) -> bool:
    return bool(value) and str(value).lower() not in {"0", "false", "none", "null"}


def build_realtime_signal_summary(
    *,
    storage_root: Path,
    execution_root: Path = DEFAULT_EXECUTION_STORAGE_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a realtime/shadow signal dashboard summary from execution evidence."""

    generated_at_utc = generated_at_utc or now_utc()
    latest = _latest_monitor_receipt(execution_root=Path(execution_root))
    if latest is None:
        chart_payload = {
            "mode": "not_started",
            "monitor": {
                "status": "not_started",
                "latest_receipt_path": None,
                "latest_updated_at_utc": None,
                "age_seconds": None,
                "cycle_count": 0,
                "failed_cycle_count": 0,
            },
            "readiness": {
                "feature_snapshot_readiness": "not_started",
                "decision_input_readiness": "not_started",
            },
            "safety": {
                "provider_calls_performed": 0,
                "broker_calls_performed": 0,
                "model_activation_performed": False,
                "broker_order_construction_performed": False,
                "account_mutation_performed": False,
            },
            "signal_cards": [
                {"label": "Monitor", "value": "Not started", "status": "not_started", "hint": "No execution-owned realtime monitor receipt exists yet."},
                {"label": "Decision handoff", "value": "Not started", "status": "not_started", "hint": "Shadow decision input will appear after monitor evidence exists."},
                {"label": "Broker mutation", "value": "Disabled", "status": "safe", "hint": "Realtime dashboard cannot place orders or mutate accounts."},
            ],
            "gaps": ["no_realtime_monitor_receipt"],
        }
        return {
            "contract_type": REALTIME_SIGNAL_SUMMARY_CONTRACT,
            "schema_version": 1,
            "generated_at_utc": generated_at_utc,
            "source_system": "trading-storage",
            "status": "not_started",
            "severity": "info",
            "summary": "Realtime signal monitoring has no execution-owned receipt yet; dashboard is showing the accepted safe empty state.",
            "chart_payload": chart_payload,
            "profile_refs": [{"registry_ref": "REALTIME_SIGNAL_SUMMARY", "field": "contract_type"}],
            "issue_refs": [],
            "diagnostic_refs": [{"ref_type": "execution_realtime_monitor_receipts", "count": 0}],
            "lineage_refs": [{"contract_type": "execution_realtime_monitor_receipt", "included": False}],
            "freshness": {"class": "realtime_signal_snapshot", "status": "fresh", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
            "schema_ref": REALTIME_SIGNAL_SUMMARY_SCHEMA_REF,
        }

    receipt_path, receipt = latest
    summary = _summary_from_receipt(receipt)
    cycles, failed_cycles = _cycle_counts(receipt)
    provider_calls = int(summary.get("provider_calls_performed") or receipt.get("provider_calls_performed") or 0)
    broker_calls = int(summary.get("broker_calls_performed") or receipt.get("broker_calls_performed") or 0)
    model_activation = _truthy(summary.get("model_activation_performed") or receipt.get("model_activation_performed"))
    order_construction = _truthy(summary.get("broker_order_construction_performed") or receipt.get("broker_order_construction_performed"))
    account_mutation = _truthy(summary.get("account_mutation_performed") or receipt.get("account_mutation_performed"))
    safety_violation = model_activation or order_construction or account_mutation or broker_calls > 0
    feature_readiness = str(summary.get("feature_snapshot_readiness") or "unknown")
    decision_readiness = str(summary.get("decision_input_readiness") or "unknown")
    live_status = str(summary.get("live_observe_status") or receipt.get("loop_status") or receipt.get("status") or "observed")
    status = "unsafe" if safety_violation else "degraded" if failed_cycles else "shadow_ready"
    severity = "critical" if safety_violation else "medium" if failed_cycles else "info"
    chart_payload = {
        "mode": "shadow_monitoring",
        "monitor": {
            "status": live_status,
            "latest_receipt_path": str(receipt_path),
            "latest_updated_at_utc": _latest_updated_at(receipt_path),
            "age_seconds": _age_seconds(receipt_path),
            "cycle_count": cycles,
            "failed_cycle_count": failed_cycles,
        },
        "readiness": {
            "feature_snapshot_readiness": feature_readiness,
            "decision_input_readiness": decision_readiness,
        },
        "safety": {
            "provider_calls_performed": provider_calls,
            "broker_calls_performed": broker_calls,
            "model_activation_performed": model_activation,
            "broker_order_construction_performed": order_construction,
            "account_mutation_performed": account_mutation,
        },
        "signal_cards": [
            {"label": "Monitor", "value": live_status, "status": status, "hint": f"{cycles} cycle(s), {failed_cycles} failed."},
            {"label": "Provider observations", "value": provider_calls, "status": "observed" if provider_calls else "not_observed", "hint": "Read-only market-data observations only."},
            {"label": "Feature snapshot", "value": feature_readiness, "status": feature_readiness, "hint": "Realtime features are parity-bound to historical model inputs."},
            {"label": "Decision handoff", "value": decision_readiness, "status": decision_readiness, "hint": "Shadow handoff only; no model activation."},
            {"label": "Broker mutation", "value": "Disabled" if not safety_violation else "Violation", "status": "safe" if not safety_violation else "unsafe", "hint": "Broker/order/account mutation must remain false."},
        ],
        "gaps": [] if provider_calls else ["no_live_provider_observation_in_latest_receipt"],
    }
    return {
        "contract_type": REALTIME_SIGNAL_SUMMARY_CONTRACT,
        "schema_version": 1,
        "generated_at_utc": generated_at_utc,
        "source_system": "trading-storage",
        "status": status,
        "severity": severity,
        "summary": "Realtime signal monitoring is summarized from execution-owned shadow evidence; broker/order/account mutation remains disabled.",
        "chart_payload": chart_payload,
        "profile_refs": [{"registry_ref": "REALTIME_SIGNAL_SUMMARY", "field": "contract_type"}],
        "issue_refs": [{"issue_type": "realtime_safety_violation", "status": "open", "severity": "critical"}] if safety_violation else [],
        "diagnostic_refs": [{"ref_type": "execution_realtime_monitor_receipt", "path": str(receipt_path), "cycle_count": cycles}],
        "lineage_refs": [{"contract_type": str(receipt.get("contract_type") or "execution_realtime_monitor_receipt"), "path": str(receipt_path), "included": True}],
        "freshness": {"class": "realtime_signal_snapshot", "status": "fresh", "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS},
        "schema_ref": REALTIME_SIGNAL_SUMMARY_SCHEMA_REF,
    }


def refresh_realtime_signal_summary_read_model(
    *,
    storage_root: Path = Path("storage"),
    execution_root: Path = DEFAULT_EXECUTION_STORAGE_ROOT,
) -> dict[str, Any]:
    storage_root.mkdir(parents=True, exist_ok=True)
    payload = build_realtime_signal_summary(storage_root=storage_root, execution_root=execution_root)
    materialized = materialize_dashboard_read_model(payload, storage_root=storage_root, expected_contract_type=REALTIME_SIGNAL_SUMMARY_CONTRACT)
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": REALTIME_SIGNAL_SUMMARY_CONTRACT,
        "materialized": materialized.index_row,
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }


def write_realtime_signal_summary(payload: Mapping[str, Any], *, output: TextIO) -> None:
    json.dump(dict(payload), output, indent=2, sort_keys=True)
    output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or refresh realtime_signal_summary from execution-owned monitor evidence.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--execution-root", type=Path, default=DEFAULT_EXECUTION_STORAGE_ROOT)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    if args.refresh:
        json.dump(
            refresh_realtime_signal_summary_read_model(storage_root=args.storage_root, execution_root=args.execution_root),
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    write_realtime_signal_summary(
        build_realtime_signal_summary(storage_root=args.storage_root, execution_root=args.execution_root),
        output=sys.stdout,
    )
    return 0


__all__ = [
    "REALTIME_SIGNAL_SUMMARY_CONTRACT",
    "build_realtime_signal_summary",
    "refresh_realtime_signal_summary_read_model",
    "write_realtime_signal_summary",
]
