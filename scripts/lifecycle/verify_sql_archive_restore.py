#!/usr/bin/env python3
"""Verify file-backed SQL archive copies without materialized database restore."""

from __future__ import annotations

from trading_storage.sql_archive import restore_main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(restore_main())
