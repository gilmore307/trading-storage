#!/usr/bin/env python3
"""Plan or apply local trading-storage retention rules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trading_storage.lifecycle import apply_retention_plan, plan_retention


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive or delete ignored local trading-storage runtime files according to conservative retention rules."
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root. Defaults to the current directory.")
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("storage/90_lifecycle/archive"),
        help="Archive destination relative to --root unless absolute. Defaults to storage/90_lifecycle/archive.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the planned archive/delete actions. Default is dry-run only.")
    args = parser.parse_args(argv)

    plan = plan_retention(root=args.root, archive_root=args.archive_root, dry_run=not args.apply)
    if args.apply:
        plan = apply_retention_plan(plan)
    sys.stdout.write(plan.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
