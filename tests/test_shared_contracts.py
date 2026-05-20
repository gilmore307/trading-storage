from __future__ import annotations

import csv
import unittest
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[1] / "main" / "shared"


class SharedContractTests(unittest.TestCase):
    def test_evaluation_primary_benchmark_candidate_csv_contract(self):
        candidate_path = SHARED_ROOT / "evaluation_primary_benchmark_candidate.csv"

        with candidate_path.open(newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))

        self.assertEqual(
            list(rows[0].keys()),
            [
                "contract_id",
                "candidate_status",
                "component_id",
                "target_symbol",
                "asset_class",
                "theme_bucket",
                "component_role",
                "start_date",
                "end_date",
                "weight",
                "time_bucket_id",
                "time_bucket_weight",
                "sector_coverage_tags",
                "event_coverage_tags",
                "market_condition_tags",
                "data_availability_tags",
                "target_context_ref",
                "stress_exception_ref",
                "training_exclusion_reason",
            ],
        )
        self.assertEqual(len(rows), 35)
        self.assertEqual({row["contract_id"] for row in rows}, {"primary_benchmark_candidate_20260519"})
        self.assertEqual({row["candidate_status"] for row in rows}, {"final_candidate_not_frozen"})
        self.assertAlmostEqual(sum(float(row["weight"]) for row in rows), 1.0)
        time_bucket_weights: dict[str, float] = {}
        for row in rows:
            time_bucket_weights.setdefault(row["time_bucket_id"], 0.0)
            time_bucket_weights[row["time_bucket_id"]] += float(row["weight"])
            self.assertTrue(row["training_exclusion_reason"])
        self.assertEqual(
            {bucket: round(weight, 2) for bucket, weight in time_bucket_weights.items()},
            {
                "time_bucket_2020_2021": 0.25,
                "time_bucket_2022": 0.25,
                "time_bucket_2023_2024": 0.25,
                "time_bucket_2025_2026": 0.25,
            },
        )
        sector_tags = {
            tag
            for row in rows
            for tag in row["sector_coverage_tags"].split(";")
            if tag
        }
        self.assertGreaterEqual(len(sector_tags), 10)
        self.assertIn("consumer_discretionary", sector_tags)
        self.assertIn("consumer_staples", sector_tags)
        self.assertIn("entertainment_media", sector_tags)
        target_symbols = {row["target_symbol"] for row in rows}
        for symbol in {"DIS", "NFLX", "TGT", "WMT", "CMG", "RBLX", "HD"}:
            self.assertIn(symbol, target_symbols)

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
        self.assertEqual(set(by_target), {"BTC", "ETH", "SOL", "AAOI"})
        self.assertEqual(by_target["BTC"][0]["layer2_context_symbol"], "BKCH")
        self.assertEqual(by_target["BTC"][0]["listed_proxy_symbol"], "IBIT")
        self.assertEqual(by_target["BTC"][0]["optionable_proxy_status"], "accepted_optionable_proxy")
        self.assertTrue(
            all(row["layer2_context_symbol"] == "BKCH" for row in by_target["BTC"] + by_target["ETH"] + by_target["SOL"])
        )
        self.assertEqual(
            {row["layer2_context_symbol"] for row in by_target["AAOI"]},
            {"AIQ", "XLK", "SMH", "XLC"},
        )
        self.assertEqual(
            {row["layer2_mapping_method_type"] for row in by_target["AAOI"]},
            {
                "primary_business_context",
                "secondary_sector_context",
                "industry_chain_context",
                "weak_demand_side_context",
            },
        )
        self.assertTrue(all(row["optionable_proxy_status"] == "not_applicable" for row in by_target["AAOI"]))

        with universe_path.open(newline="") as csv_file:
            universe_symbols = {row["symbol"] for row in csv.DictReader(csv_file)}
        with combinations_path.open(newline="") as csv_file:
            combination_ids = {row["combination_id"] for row in csv.DictReader(csv_file)}
        for proxy in {"IBIT", "ETHA", "FSOL"}:
            self.assertNotIn(proxy, universe_symbols)
            self.assertFalse(any(proxy.lower() in combination_id for combination_id in combination_ids))


if __name__ == "__main__":
    unittest.main()
