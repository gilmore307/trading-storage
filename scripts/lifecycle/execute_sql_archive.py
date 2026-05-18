#!/usr/bin/env python3
"""Plan or execute reviewed file-backed SQL archive copies."""

from __future__ import annotations

from trading_storage.sql_archive import archive_main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(archive_main())
