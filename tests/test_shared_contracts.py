from __future__ import annotations

import csv
import unittest
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[1] / "main" / "shared"


class SharedContractTests(unittest.TestCase):
    def test_target_layer2_context_mapping_keeps_crypto_proxies_out_of_layer_context(self):
        mapping_path = SHARED_ROOT / "layer_2_target_context_mapping.csv"
        universe_path = SHARED_ROOT / "layer_1_2_market_context_etf_universe.csv"
        combinations_path = SHARED_ROOT / "layer_1_2_market_context_relative_strength_combinations.csv"

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
        by_target = {row["target_symbol"]: row for row in mapping_rows}
        self.assertEqual(set(by_target), {"BTC", "ETH", "SOL"})
        self.assertEqual(by_target["BTC"]["layer2_context_symbol"], "BKCH")
        self.assertEqual(by_target["BTC"]["listed_proxy_symbol"], "IBIT")
        self.assertEqual(by_target["BTC"]["optionable_proxy_status"], "accepted_optionable_proxy")
        self.assertTrue(
            all(row["layer2_context_symbol"] == "BKCH" for row in mapping_rows)
        )

        with universe_path.open(newline="") as csv_file:
            universe_symbols = {row["symbol"] for row in csv.DictReader(csv_file)}
        with combinations_path.open(newline="") as csv_file:
            combination_ids = {row["combination_id"] for row in csv.DictReader(csv_file)}
        for proxy in {"IBIT", "ETHA", "FSOL"}:
            self.assertNotIn(proxy, universe_symbols)
            self.assertFalse(any(proxy.lower() in combination_id for combination_id in combination_ids))


if __name__ == "__main__":
    unittest.main()
