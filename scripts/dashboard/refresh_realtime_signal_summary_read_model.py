#!/usr/bin/env python3
"""Refresh the storage-hosted realtime_signal_summary dashboard read model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trading_storage.dashboard_realtime_signals import DEFAULT_TRADING_EXECUTION_ROOT, refresh_realtime_signal_summary_read_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh realtime_signal_summary.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--execution-root", type=Path, default=DEFAULT_TRADING_EXECUTION_ROOT)
    args = parser.parse_args(argv)
    json.dump(
        refresh_realtime_signal_summary_read_model(storage_root=args.storage_root, execution_root=args.execution_root),
        sys.stdout,
        indent=2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
