#!/usr/bin/env python3
"""Validate and materialize a storage-hosted dashboard read-model JSON document."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping

from trading_storage.dashboard_read_models import materialize_dashboard_read_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a dashboard read-model envelope and write snapshot/latest/index files under storage/dashboard_cache."
    )
    parser.add_argument("payload", type=Path, help="Dashboard read-model JSON payload.")
    parser.add_argument("--contract-type", help="Expected contract_type; rejects mismatched payloads.")
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    args = parser.parse_args(argv)

    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit("payload must be a JSON object")
    materialized = materialize_dashboard_read_model(
        payload,
        storage_root=args.storage_root,
        expected_contract_type=args.contract_type,
    )
    sys.stdout.write(json.dumps(materialized.index_row, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
