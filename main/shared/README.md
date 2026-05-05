# shared

Trading-wide reusable static files live here when they are not templates.

Use this folder for reviewed cross-project files such as shared vocabularies, lookup tables, examples, or other static assets that multiple repositories may reference. Do not store secrets, generated runtime outputs, caches, or component-owned implementation files here.

Current files:

- `market_regime_etf_universe.csv` — curated ETF universe for market-state and U.S. sector/industry/theme observation. `model_layer` is the authoritative Layer 1 / Layer 2 scope discriminator: `layer_01_market_regime` rows feed Layer 1 market-context construction, while `layer_02_sector_context` rows feed Layer 2 sector/industry/theme observation and holdings analysis. `bar_grain` is the intended source acquisition/detail granularity, not necessarily the downstream derived feature cadence.
- `market_regime_relative_strength_combinations.csv` — curated market-context relative-strength combinations. `model_layer` is the authoritative scope discriminator: `layer_01_market_regime` rows feed Layer 1 broad market/cross-asset evidence; `layer_02_sector_context` rows feed Layer 2 sector-context evidence. Each row defines `numerator_symbol / denominator_symbol`, `combination_type`, source bar grains, `feature_bar_grain`, and `interpretation`. Generated feature values do not belong here. Its columns are registered in `trading-manager`.
