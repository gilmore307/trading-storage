import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.lifecycle.consolidate_trading_economics_source import execute_consolidation


class TradingEconomicsSourceConsolidationTests(unittest.TestCase):
    def _write_source_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["event_time", "country", "event"])
            writer.writeheader()
            writer.writerows(rows)

    def test_consolidates_legacy_roots_into_monthly_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source_data = Path(td) / "storage" / "01_source_data"
            self._write_source_csv(
                source_data / "monthly_backfill" / "trading_economics_calendar_web" / "2026-05" / "runs" / "old_monthly" / "saved" / "trading_economics_calendar_event.csv",
                [{"event_time": "2026-05-26T08:30:00-04:00", "country": "United States", "event": "Durable Goods Orders"}],
            )
            self._write_source_csv(
                source_data / "realtime" / "trading_economics_calendar_web" / "runs" / "rt_run" / "saved" / "trading_economics_calendar_event.csv",
                [
                    {"event_time": "2026-06-05T08:30:00-04:00", "country": "United States", "event": "Non Farm Payrolls"},
                    {"event_time": "Friday June 05 2026", "country": "United States", "event": "Rejected Date Only"},
                ],
            )
            summary = execute_consolidation(source_data, "unit", execute=True)

            canonical = source_data / "monthly_backfill" / "trading_economics_calendar_web"
            self.assertFalse((source_data / "realtime" / "trading_economics_calendar_web").exists())
            self.assertEqual(summary["accepted_rows"], 2)
            self.assertEqual(summary["rejected_rows"], 1)
            self.assertTrue(list((canonical / "2026-05" / "runs").glob("monthly_old_monthly_*")))
            self.assertTrue(list((canonical / "2026-06" / "runs").glob("realtime_rt_run_*")))
            manifest = json.loads((canonical / "_manifests" / "source_consolidation_unit" / "manifest.json").read_text())
            self.assertEqual(manifest["active_layout"], "storage/01_source_data/monthly_backfill/trading_economics_calendar_web/YYYY-MM/runs/<run_id>/{saved,cleaned,request_manifest.json,completion_receipt.json}")
            rejected = (canonical / "_manifests" / "source_consolidation_unit" / "rejected_rows.csv").read_text()
            self.assertIn("Rejected Date Only", rejected)


if __name__ == "__main__":
    unittest.main()
