#!/usr/bin/env python3
"""Run the storage-owned scheduled maintenance pass."""

from __future__ import annotations

from trading_storage.storage_maintenance import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
