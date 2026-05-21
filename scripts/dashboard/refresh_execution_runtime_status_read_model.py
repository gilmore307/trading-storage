#!/usr/bin/env python3
"""Refresh the execution realtime runtime status dashboard read model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_storage.dashboard_execution_runtime import DEFAULT_EXECUTION_STATUS_PATH, refresh_execution_runtime_status_read_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--status-path", type=Path, default=DEFAULT_EXECUTION_STATUS_PATH)
    args = parser.parse_args()
    result = refresh_execution_runtime_status_read_model(storage_root=args.storage_root, status_path=args.status_path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
