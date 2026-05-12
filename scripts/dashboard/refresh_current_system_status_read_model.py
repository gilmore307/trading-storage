#!/usr/bin/env python3
"""Refresh the storage-owned current_system_status_summary_v1 read model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_storage.dashboard_system_status import refresh_current_system_status_read_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh current_system_status_summary_v1 dashboard read model.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    args = parser.parse_args(argv)
    result = refresh_current_system_status_read_model(storage_root=args.storage_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
