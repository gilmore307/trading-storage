#!/usr/bin/env python3
"""Store a component completion receipt payload as a storage-owned artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping

from trading_storage.artifact_store import store_completion_receipt_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store component_completion_receipt_payload JSON and emit artifact_ref metadata.")
    parser.add_argument("receipt", type=Path, help="Component completion receipt JSON payload.")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--producer-repo", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    args = parser.parse_args(argv)

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    if not isinstance(receipt, Mapping):
        raise SystemExit("receipt must be a JSON object")
    stored = store_completion_receipt_payload(
        receipt,
        request_id=args.request_id,
        run_id=args.run_id,
        producer_repo=args.producer_repo,
        workflow_id=args.workflow_id,
        storage_root=args.storage_root,
    )
    sys.stdout.write(json.dumps(stored.artifact_ref, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
