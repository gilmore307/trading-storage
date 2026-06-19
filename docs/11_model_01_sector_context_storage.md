# M01 Sector Context Storage

This file records the `trading-storage` view of M02 persistence. Semantic construction belongs to `trading-data` and `trading-model`; global naming authority belongs to `trading-manager`.

## Durable artifact names

Accepted M02 physical destinations should preserve these canonical names:

```text
trading_data.m02_sector_context_feature_generation
trading_model.m02_sector_context_model_generation
trading_model.m02_sector_context_model_generation_explainability
trading_model.m02_sector_context_model_generation_diagnostics
```

There is no separate M02 source storage artifact. The conceptual M02 model output is per-ETF `context_etf_state`; the current physical table is `trading_model.m02_sector_context_model_generation` with the `sector_context_state` vocabulary.

M02 sector context is restricted to the 11 broad Select Sector SPDR anchor ETFs plus the `BKCH` crypto context-anchor exception in `main/shared/model_01_background_context_etf_universe.csv`. Focused industry-chain and theme ETFs such as semiconductor, cybersecurity, ARK, biotech, retail, and similar funds are not M02 sector anchors. They are outside the current M02 contract unless a later reviewed proxy/theme layer is introduced.

ETF holdings are not the candidate universe. Ordinary equity candidates come from the reviewed total-symbol pool and target metadata, while M02 supplies the broad sector anchor state attached to those candidates.

## Storage boundary

Storage contracts preserve point-in-time availability, row keys, restore/rehydrate expectations, retention policy, and completion receipts. They do not decide model semantics or promote explainability or diagnostics fields into downstream dependencies.

M02 storage should distinguish:

- per-sector-anchor `context_etf_state` rows, currently stored through `m02_sector_context_model_generation`;
- optional global/group `cross_etf_summary` rows or artifacts;
- internal per-ETF cross-section calculations, which should not become separate durable output rows when embedded in `context_etf_state`;
- target routing evidence for M01 ETF targets, M02 context ETF targets, and ordinary targets.

## Column naming

Generic identity, lineage, timestamp, and receipt columns may remain generic. Model-owned model columns use canonical compact `2_*` names. SQL DDL should quote numeric-leading identifiers where required instead of inventing `layer02_*` semantic aliases. The active `m02_sector_context_model_generation` column set uses signed direction, direction-neutral trend/tradability, transition risk, separate handoff state/bias, coverage, data-quality, and evidence-count fields; readiness aliases such as `2_selection_readiness_score` are not durable storage contract columns.

## Stage flow

```mermaid
flowchart LR
    contracts["accepted M02 contracts<br/>feature, model, explainability, diagnostics"]
    layout["storage layout / SQL destination<br/>point-in-time durable persistence"]
    policy["retention, restore, rehydrate<br/>backup and reference rules"]
    consumers["data/model/manager/dashboard consumers<br/>dereference accepted artifacts"]

    contracts --> layout --> policy --> consumers
```

## Acceptance

M02 storage changes are acceptable when they:

- preserve canonical M02 artifact names and point-in-time availability;
- avoid adding a separate M02 source artifact unless a later accepted contract creates it;
- keep M02 sector context restricted to broad sector anchors plus the crypto context-anchor exception, not focused industry/theme ETFs;
- keep ETF holdings out of ordinary equity candidate-universe definition;
- avoid durable `context_etf_cross_section_row` output rows when their values are construction evidence already embedded in `context_etf_state`;
- preserve the three target-context routing cases before introducing new storage tables for `target_context_profile`;
- define durable layout, reference, retention, restore, and rehydrate expectations before producers depend on them;
- route shared fields, statuses, artifact-reference formats, or storage contract names through `trading-manager/scripts/` before cross-repository dependence.

Current verification:

```bash
git status --short
find docs -maxdepth 1 -type f | sort
find . -maxdepth 2 -type f | sort
git diff --check
```
