# shared

Trading-wide reusable static files live here when they are not templates.

Use this folder for reviewed cross-project files such as shared vocabularies, lookup tables, examples, or other static assets that multiple repositories may reference. Do not store secrets, generated runtime outputs, caches, or component-owned implementation files here.

Current files:

- `market_regime_etf_universe.csv` — curated ETF universe for market-state and sector/industry/theme observation. `bar_grain` is the intended source acquisition/detail granularity, not necessarily the downstream derived feature cadence. Layer 1 V1 derived regime features use `feature_grain = 30m`. `market_state_etf` rows are Layer 1 regime/bar instruments, including equal-weight/core equity and rates-curve symbols needed for V1 ratios; only `sector_observation_etf` rows require holdings analysis for Layer 2 security-selection exposure.
- `market_regime_relative_strength_combinations.csv` — curated Layer 1 V1 relative-strength combinations. Each row defines `numerator_symbol / denominator_symbol`, `combination_type`, source bar grains, `feature_bar_grain`, and `interpretation`. The file is a reviewed planning/contract surface for `trading-derived`; generated feature values do not belong here. Its columns are registered in `trading-main`.
