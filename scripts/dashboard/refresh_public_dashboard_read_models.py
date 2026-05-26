#!/usr/bin/env python3
"""Refresh the public dashboard read models served to trading-dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from trading_storage.artifact_store import now_utc
from trading_storage.dashboard_event_calendar import EVENT_CALENDAR_SUMMARY_CONTRACT, refresh_event_calendar_summary_read_model
from trading_storage.dashboard_execution_runtime import DEFAULT_EXECUTION_STATUS_PATH, EXECUTION_RUNTIME_STATUS_CONTRACT, refresh_execution_runtime_status_read_model
from trading_storage.dashboard_refresh import DEFAULT_TRADING_MANAGER_ROOT, HISTORICAL_TASK_PROGRESS_CONTRACT, refresh_historical_task_progress_read_model
from trading_storage.dashboard_realtime_signals import DEFAULT_TRADING_EXECUTION_ROOT, REALTIME_SIGNAL_SUMMARY_CONTRACT, refresh_realtime_signal_summary_read_model
from trading_storage.dashboard_system_status import CURRENT_SYSTEM_STATUS_CONTRACT, refresh_current_system_status_read_model


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
            EVENT_CALENDAR_SUMMARY_CONTRACT,
            lambda: refresh_event_calendar_summary_read_model(storage_root=args.storage_root),
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
    ]
    status = "succeeded" if all(row.get("status") == "succeeded" for row in results) else "degraded"
    print(
        json.dumps(
            {"contract_type": "dashboard_read_model_refresh_batch_receipt", "status": status, "results": results},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if any(row.get("status") == "succeeded" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
