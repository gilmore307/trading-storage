#!/usr/bin/env python3
"""Refresh the public dashboard read models served to trading-dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_storage.dashboard_refresh import DEFAULT_TRADING_MANAGER_ROOT, refresh_historical_task_progress_read_model
from trading_storage.dashboard_system_status import refresh_current_system_status_read_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh public storage-hosted dashboard read models.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--trading-manager-root", type=Path, default=DEFAULT_TRADING_MANAGER_ROOT)
    args = parser.parse_args(argv)
    results = [
        refresh_current_system_status_read_model(storage_root=args.storage_root),
        refresh_historical_task_progress_read_model(
            trading_manager_root=args.trading_manager_root,
            storage_root=args.storage_root,
        ).receipt,
    ]
    print(json.dumps({"contract_type": "dashboard_read_model_refresh_batch_receipt", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
