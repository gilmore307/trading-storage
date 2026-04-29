# shared

Trading-wide reusable static files live here when they are not templates.

Use this folder for reviewed cross-project files such as shared vocabularies, lookup tables, examples, or other static assets that multiple repositories may reference. Do not store secrets, generated runtime outputs, caches, or component-owned implementation files here.

Current files:

- `market_etf_universe.csv` — curated ETF universe for market-state and sector/industry/theme observation. `bar_grain` is the intended observation granularity.
