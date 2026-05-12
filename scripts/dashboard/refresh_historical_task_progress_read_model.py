#!/usr/bin/env python3
"""Refresh historical_task_progress_summary into storage/dashboard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trading_storage.dashboard_refresh import DEFAULT_TRADING_MANAGER_ROOT, refresh_historical_task_progress_read_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the manager semantic producer and materialize historical_task_progress_summary under storage/dashboard."
    )
    parser.add_argument("--trading-manager-root", type=Path, default=DEFAULT_TRADING_MANAGER_ROOT)
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--stage-coverage-path", type=Path, help="Optional manager_stage_coverage JSON evidence for the producer.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    result = refresh_historical_task_progress_read_model(
        trading_manager_root=args.trading_manager_root,
        storage_root=args.storage_root,
        stage_coverage_path=args.stage_coverage_path,
        timeout_seconds=args.timeout_seconds,
    )
    sys.stdout.write(json.dumps(result.receipt, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
