#!/usr/bin/env python3
"""Consolidate Trading Economics source rows into one month-bucketed root."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


FIELDS = [
    "event_time",
    "country",
    "event",
    "source_event_type",
    "reference",
    "actual",
    "previous",
    "consensus",
    "te_forecast",
    "revised",
    "importance",
    "symbol",
    "source_url",
]
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SourceCsv:
    label: str
    path: Path
    run_id: str


def _default_source_data_root() -> Path:
    return Path("/root/projects/trading-storage/storage/01_source_data")


def _canonical_root(source_data_root: Path) -> Path:
    return source_data_root / "monthly_backfill" / "trading_economics_calendar_web"


def _legacy_roots(source_data_root: Path) -> dict[str, Path]:
    return {
        "realtime": source_data_root / "realtime" / "trading_economics_calendar_web",
        "replay": source_data_root / "replay" / "trading_economics_calendar_web",
    }


def _is_month_dir(path: Path) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}", path.name))


def _run_id_for(path: Path) -> str:
    parts = path.parts
    if "runs" in parts:
        idx = len(parts) - 1 - list(reversed(parts)).index("runs")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return path.parent.parent.name


def discover_source_csvs(source_data_root: Path) -> list[SourceCsv]:
    canonical = _canonical_root(source_data_root)
    result: list[SourceCsv] = []
    if canonical.exists():
        for month_dir in sorted(path for path in canonical.iterdir() if path.is_dir() and _is_month_dir(path)):
            for csv_path in sorted(month_dir.glob("runs/*/saved/trading_economics_calendar_event.csv")):
                result.append(SourceCsv("monthly", csv_path, _run_id_for(csv_path)))
    for label, root in _legacy_roots(source_data_root).items():
        if not root.exists():
            continue
        for csv_path in sorted(root.glob("**/saved/trading_economics_calendar_event.csv")):
            result.append(SourceCsv(label, csv_path, _run_id_for(csv_path)))
    return result


def parse_event_time(value: str) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, "blank_event_time"
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern).replace(tzinfo=ET)
                break
            except ValueError:
                continue
    if parsed is None:
        return None, "unparseable_or_date_only_event_time"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ET)
    return parsed.isoformat(), None


def _safe_run_id(label: str, run_id: str, path: Path) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._-") or "run"
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:10]
    return f"{label}_{safe}_{digest}"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def load_rows(source_csvs: list[SourceCsv]) -> tuple[dict[tuple[str, str], list[dict[str, str]]], list[dict[str, str]], dict[str, int]]:
    buckets: dict[tuple[str, str], list[dict[str, str]]] = {}
    rejected: list[dict[str, str]] = []
    counts = {"source_csv_count": len(source_csvs), "accepted_rows": 0, "rejected_rows": 0}
    for source in source_csvs:
        run_key = _safe_run_id(source.label, source.run_id, source.path)
        with source.path.open(newline="", encoding="utf-8") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                normalized_time, error = parse_event_time(str(row.get("event_time") or ""))
                if error is not None or normalized_time is None:
                    rejected.append(
                        {
                            "source_label": source.label,
                            "source_path": str(source.path),
                            "source_run_id": source.run_id,
                            "row_number": str(row_number),
                            "event_time": str(row.get("event_time") or ""),
                            "event": str(row.get("event") or ""),
                            "reason": error or "unknown_event_time_error",
                        }
                    )
                    counts["rejected_rows"] += 1
                    continue
                clean_row = {field: str(row.get(field) or "") for field in FIELDS}
                clean_row["event_time"] = normalized_time
                month = normalized_time[:7]
                buckets.setdefault((month, run_key), []).append(clean_row)
                counts["accepted_rows"] += 1
    return buckets, rejected, counts


def _move_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"archive target already exists: {target}")
    source.rename(target)
    return True


def execute_consolidation(source_data_root: Path, stamp: str, *, execute: bool) -> dict[str, Any]:
    canonical = _canonical_root(source_data_root)
    source_csvs = discover_source_csvs(source_data_root)
    buckets, rejected, counts = load_rows(source_csvs)
    manifest_root = canonical / "_manifests" / f"source_consolidation_{stamp}"
    summary: dict[str, Any] = {
        "contract_type": "trading_economics_source_consolidation_manifest",
        "stamp": stamp,
        "execute": execute,
        "source_data_root": str(source_data_root),
        "canonical_root": str(canonical),
        "source_csv_count": counts["source_csv_count"],
        "accepted_rows": counts["accepted_rows"],
        "rejected_rows": counts["rejected_rows"],
        "month_count": len({month for month, _ in buckets}),
        "run_bucket_count": len(buckets),
        "legacy_roots_moved": [],
        "monthly_originals_moved": False,
        "active_layout": "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/YYYY-MM/runs/<run_id>/{saved,cleaned,request_manifest.json,completion_receipt.json}",
    }
    if not execute:
        return summary
    if not canonical.exists():
        raise FileNotFoundError(f"canonical root does not exist: {canonical}")
    original_monthly = manifest_root / "original_roots" / "monthly_backfill"
    for child in sorted(list(canonical.iterdir())):
        if _is_month_dir(child) or child.name in {"_recent_refresh_runs", "_recent_refresh_completion_receipt.json"}:
            _move_if_exists(child, original_monthly / child.name)
            summary["monthly_originals_moved"] = True
    for label, root in _legacy_roots(source_data_root).items():
        if _move_if_exists(root, manifest_root / "original_roots" / label):
            summary["legacy_roots_moved"].append(str(root))
    for (month, run_key), rows in sorted(buckets.items()):
        run_dir = canonical / month / "runs" / run_key
        saved_path = run_dir / "saved" / "trading_economics_calendar_event.csv"
        cleaned_path = run_dir / "cleaned" / "trading_economics_calendar_event.jsonl"
        _write_csv(saved_path, rows)
        _write_jsonl(cleaned_path, rows)
        _write_json(run_dir / "cleaned" / "schema.json", {"trading_economics_calendar_event": FIELDS, "row_count": len(rows)})
        _write_json(
            run_dir / "request_manifest.json",
            {
                "feed": "07_feed_trading_economics_calendar_web",
                "month": month,
                "row_count": len(rows),
                "source_consolidation_manifest": str((manifest_root / "manifest.json").resolve()),
                "persistence": "canonical month-bucketed Trading Economics source rows",
            },
        )
        receipt = {
            "feed": "07_feed_trading_economics_calendar_web",
            "task_id": "trading_economics_source_consolidation",
            "runs": [
                {
                    "run_id": run_key,
                    "status": "succeeded",
                    "output_dir": str(run_dir),
                    "outputs": [str(saved_path), str(cleaned_path)],
                    "row_counts": {"trading_economics_calendar_event": len(rows)},
                    "error": None,
                }
            ],
        }
        _write_json(run_dir / "completion_receipt.json", receipt)
    by_month: dict[str, int] = {}
    for (month, _), rows in buckets.items():
        by_month[month] = by_month.get(month, 0) + len(rows)
    with (manifest_root / "coverage_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["month", "row_count"])
        writer.writeheader()
        for month, row_count in sorted(by_month.items()):
            writer.writerow({"month": month, "row_count": row_count})
    with (manifest_root / "rejected_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_label", "source_path", "source_run_id", "row_number", "event_time", "event", "reason"])
        writer.writeheader()
        writer.writerows(rejected)
    _write_json(manifest_root / "manifest.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data-root", type=Path, default=_default_source_data_root())
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%dT%H%M%S"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    summary = execute_consolidation(args.source_data_root, args.stamp, execute=args.execute)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
