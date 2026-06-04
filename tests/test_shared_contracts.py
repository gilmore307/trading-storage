from __future__ import annotations

import csv
import unittest
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[1] / "main" / "shared"


class SharedContractTests(unittest.TestCase):
    def test_target_layer2_context_mapping_keeps_crypto_proxies_out_of_layer_context(self):
        mapping_path = SHARED_ROOT / "layer_02_target_context_mapping.csv"
        universe_path = SHARED_ROOT / "layer_01_02_market_context_etf_universe.csv"
        combinations_path = SHARED_ROOT / "layer_01_02_market_context_relative_strength_combinations.csv"

        with mapping_path.open(newline="") as csv_file:
            mapping_rows = list(csv.DictReader(csv_file))
        self.assertEqual(
            list(mapping_rows[0].keys()),
            [
                "target_symbol",
                "target_asset_class",
                "spot_ref",
                "layer2_context_symbol",
                "layer2_mapping_method_type",
                "listed_proxy_symbol",
                "optionable_proxy_symbol",
                "optionable_proxy_status",
                "proxy_role_type",
                "proxy_use",
                "review_status",
                "interpretation",
            ],
        )
        by_target: dict[str, list[dict[str, str]]] = {}
        for row in mapping_rows:
            by_target.setdefault(row["target_symbol"], []).append(row)
        self.assertEqual(set(by_target), {"BTC", "ETH", "SOL", "AAPL", "AAOI"})
        self.assertEqual(by_target["BTC"][0]["layer2_context_symbol"], "BKCH")
        self.assertEqual(by_target["BTC"][0]["listed_proxy_symbol"], "IBIT")
        self.assertEqual(by_target["BTC"][0]["optionable_proxy_status"], "accepted_optionable_proxy")
        self.assertTrue(
            all(row["layer2_context_symbol"] == "BKCH" for row in by_target["BTC"] + by_target["ETH"] + by_target["SOL"])
        )
        self.assertEqual(
            {row["layer2_context_symbol"] for row in by_target["AAOI"]},
            {"XLK", "XLC"},
        )
        self.assertEqual(
            {row["layer2_mapping_method_type"] for row in by_target["AAOI"]},
            {
                "primary_sector_context",
                "weak_demand_side_context",
            },
        )
        self.assertEqual(by_target["AAPL"][0]["layer2_context_symbol"], "XLK")
        self.assertEqual(by_target["AAPL"][0]["layer2_mapping_method_type"], "primary_sector_context")
        self.assertEqual(by_target["AAPL"][0]["proxy_role_type"], "no_auxiliary_proxy_type")
        self.assertTrue(all(row["optionable_proxy_status"] == "not_applicable" for row in by_target["AAOI"]))

        with universe_path.open(newline="") as csv_file:
            universe_rows = list(csv.DictReader(csv_file))
            universe_symbols = {row["symbol"] for row in universe_rows}
        with combinations_path.open(newline="") as csv_file:
            combination_rows = list(csv.DictReader(csv_file))
            combination_ids = {row["combination_id"] for row in combination_rows}
        for proxy in {"IBIT", "ETHA", "FSOL"}:
            self.assertNotIn(proxy, universe_symbols)
            self.assertFalse(any(proxy.lower() in combination_id for combination_id in combination_ids))

        self.assertEqual({row["feature_grain"] for row in universe_rows}, {"1m"})
        self.assertEqual({row["numerator_bar_grain"] for row in combination_rows}, {"1m"})
        self.assertEqual({row["denominator_bar_grain"] for row in combination_rows}, {"1m"})
        self.assertEqual({row["feature_bar_grain"] for row in combination_rows}, {"1m"})

    def test_equity_total_symbol_pool_contract_exists(self):
        pool_path = SHARED_ROOT / "equity_total_symbol_pool.csv"
        symbols_path = SHARED_ROOT / "equity_total_symbol_pool.symbols.txt"

        with pool_path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = list(reader)

        self.assertEqual(
            reader.fieldnames,
            [
                "symbol",
                "name",
                "sector",
                "optionable_underlying_status",
                "pool_membership_status",
                "pool_membership_reason",
                "in_dollar_volume_top300",
                "in_market_cap_top300",
                "dollar_volume_rank",
                "market_cap_rank",
                "source_refs",
                "as_of_date",
            ],
        )
        self.assertTrue(symbols_path.exists())
        self.assertGreater(len(rows), 0)
        self.assertTrue(
            {row["optionable_underlying_status"] for row in rows}.issubset(
                {"accepted_optionable", "uncertain_verify_before_use", "no_listed_options_or_unverified"}
            )
        )
        self.assertTrue({row["pool_membership_status"] for row in rows}.issubset({"active", "inactive"}))
        symbols = [line.strip() for line in symbols_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(symbols, [row["symbol"] for row in rows if row["pool_membership_status"] == "active"])
        self.assertTrue(any("tradingview_screener_snapshot:" in row["source_refs"] for row in rows))

    def test_historical_candidate_universe_contract_exists(self):
        universe_path = SHARED_ROOT / "historical_candidate_universe.csv"
        symbols_path = SHARED_ROOT / "historical_candidate_universe.symbols.txt"

        with universe_path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = list(reader)

        self.assertEqual(
            reader.fieldnames,
            [
                "symbol",
                "target_ref",
                "asset_class",
                "instrument_type",
                "name",
                "tradingview_sector",
                "layer2_context_symbol",
                "layer2_context_method",
                "optionable_underlying_status",
                "replay_candidate_status",
                "replay_candidate_reason",
                "source_pool_as_of_date",
                "in_dollar_volume_top300",
                "in_market_cap_top300",
                "dollar_volume_rank",
                "market_cap_rank",
                "source_refs",
                "freeze_as_of_date",
                "universe_policy_ref",
            ],
        )
        self.assertTrue(symbols_path.exists())
        self.assertGreater(len(rows), 0)
        self.assertEqual({row["replay_candidate_status"] for row in rows}, {"active"})
        self.assertEqual({row["universe_policy_ref"] for row in rows}, {"fixed_current_realtime_pool_snapshot_for_historical_replay"})
        self.assertEqual({row["layer2_context_symbol"] for row in rows if row["asset_class"] == "crypto_spot"}, {"BKCH"})
        self.assertEqual({row["symbol"] for row in rows if row["asset_class"] == "crypto_spot"}, {"BTC", "ETH", "SOL"})
        self.assertTrue({row["layer2_context_symbol"] for row in rows if row["asset_class"] == "us_equity"}.issubset({"BKCH", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"}))
        symbols = [line.strip() for line in symbols_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(symbols, [row["symbol"] for row in rows])


if __name__ == "__main__":
    unittest.main()
