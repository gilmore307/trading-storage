#!/usr/bin/env python3
"""Refresh the public dashboard read models served to trading-dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from trading_storage.artifact_store import now_utc
from trading_storage.dashboard_snapshot_lifecycle import build_dashboard_snapshot_lifecycle_plan
from trading_storage.dashboard_execution_runtime import DEFAULT_EXECUTION_STATUS_PATH, EXECUTION_RUNTIME_STATUS_CONTRACT, refresh_execution_runtime_status_read_model
from trading_storage.dashboard_models import (
    MODEL_READINESS_CONTRACT,
    MODEL_PROMOTION_POSTURE_CONTRACT,
    refresh_model_readiness_summary_read_model,
    refresh_model_promotion_posture_summary_read_model,
)
from trading_storage.dashboard_refresh import DEFAULT_TRADING_MANAGER_ROOT, HISTORICAL_TASK_PROGRESS_CONTRACT, refresh_historical_task_progress_read_model
from trading_storage.dashboard_realtime_signals import DEFAULT_TRADING_EXECUTION_ROOT, REALTIME_SIGNAL_SUMMARY_CONTRACT, refresh_realtime_signal_summary_read_model
from trading_storage.dashboard_system_status import CURRENT_SYSTEM_STATUS_CONTRACT, refresh_current_system_status_read_model
from trading_storage.dashboard_temporal_explorer import TEMPORAL_EXPLORER_SUMMARY_CONTRACT, refresh_temporal_explorer_summary_read_model


def _failure_receipt(*, contract_type: str, exc: BaseException) -> dict[str, Any]:
    return {
        "contract_type": "dashboard_read_model_refresh_receipt",
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": contract_type,
        "status": "failed",
        "failure": {"error_type": exc.__class__.__name__, "message": str(exc)},
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": False,
        },
    }


def _run_one(contract_type: str, refresh: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        receipt = refresh()
    except Exception as exc:  # noqa: BLE001 - batch receipts must degrade instead of tracebacking
        return _failure_receipt(contract_type=contract_type, exc=exc)
    return {"status": "succeeded", **receipt}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh public storage-hosted dashboard read models.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--trading-manager-root", type=Path, default=DEFAULT_TRADING_MANAGER_ROOT)
    parser.add_argument("--trading-execution-root", type=Path, default=DEFAULT_TRADING_EXECUTION_ROOT)
    parser.add_argument("--execution-runtime-status-path", type=Path, default=DEFAULT_EXECUTION_STATUS_PATH)
    parser.add_argument(
        "--allow-partial-success",
        action="store_true",
        help="Return exit code 0 for a degraded batch. Default is nonzero so service monitors can alert on stale read models.",
    )
    args = parser.parse_args(argv)
    args.storage_root.mkdir(parents=True, exist_ok=True)
    results = [
        _run_one(
            CURRENT_SYSTEM_STATUS_CONTRACT,
            lambda: refresh_current_system_status_read_model(storage_root=args.storage_root),
        ),
        _run_one(
            HISTORICAL_TASK_PROGRESS_CONTRACT,
            lambda: refresh_historical_task_progress_read_model(
                trading_manager_root=args.trading_manager_root,
                storage_root=args.storage_root,
            ).receipt,
        ),
        _run_one(
            TEMPORAL_EXPLORER_SUMMARY_CONTRACT,
            lambda: refresh_temporal_explorer_summary_read_model(storage_root=args.storage_root),
        ),
        _run_one(
            REALTIME_SIGNAL_SUMMARY_CONTRACT,
            lambda: refresh_realtime_signal_summary_read_model(
                execution_root=args.trading_execution_root,
                storage_root=args.storage_root,
            ),
        ),
        _run_one(
            EXECUTION_RUNTIME_STATUS_CONTRACT,
            lambda: refresh_execution_runtime_status_read_model(
                storage_root=args.storage_root,
                status_path=args.execution_runtime_status_path,
            ),
        ),
        _run_one(
            MODEL_READINESS_CONTRACT,
            lambda: refresh_model_readiness_summary_read_model(storage_root=args.storage_root),
        ),
        _run_one(
            MODEL_PROMOTION_POSTURE_CONTRACT,
            lambda: refresh_model_promotion_posture_summary_read_model(storage_root=args.storage_root),
        ),
    ]
    maintenance: dict[str, Any] = {}
    maintenance_failed = False
    try:
        prune_receipt = build_dashboard_snapshot_lifecycle_plan(
            storage_root=args.storage_root,
            apply=True,
            approval_ref="dashboard_refresh_auto_prune:latest_only",
        )
        maintenance["dashboard_snapshot_prune_summary"] = prune_receipt.summary
    except Exception as exc:  # noqa: BLE001 - maintenance failure should be explicit in the batch receipt
        maintenance_failed = True
        maintenance["dashboard_snapshot_prune_failure"] = {
            "error_type": exc.__class__.__name__,
            "message": str(exc),
        }
    status = "succeeded" if all(row.get("status") == "succeeded" for row in results) else "degraded"
    if maintenance_failed:
        status = "degraded"
    print(
        json.dumps(
            {
                "contract_type": "dashboard_read_model_refresh_batch_receipt",
                "status": status,
                "results": results,
                "maintenance": maintenance,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if status == "succeeded":
        return 0
    return 0 if args.allow_partial_success and any(row.get("status") == "succeeded" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
