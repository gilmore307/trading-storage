# M01 Background Context Storage

This file records the `trading-storage` view of M01 persistence. Semantic construction belongs to `trading-data` and `trading-model`; global naming authority belongs to `trading-manager`.

## Durable artifact names

Accepted M01 physical destinations should preserve these canonical names:

```text
trading_data.m01_market_regime_data_acquisition
trading_data.m01_market_regime_feature_generation
trading_model.m01_market_regime_model_generation
trading_model.m01_market_regime_model_generation_explainability
trading_model.m01_market_regime_model_generation_diagnostics
```

## Storage boundary

Storage contracts preserve point-in-time availability, row keys, restore/rehydrate expectations, retention policy, and completion receipts. They do not decide model semantics or promote explainability fields into downstream dependencies.

## Column naming

Generic identity, lineage, timestamp, and receipt columns may remain generic. Model-owned model columns use canonical compact `1_*` names. SQL DDL should quote numeric-leading identifiers where required instead of inventing `layer01_*` semantic aliases.

## Stage flow

```mermaid
flowchart LR
    contracts["accepted M01 contracts<br/>source, feature, model, explainability, diagnostics"]
    layout["storage layout / SQL destination<br/>point-in-time durable persistence"]
    policy["retention, restore, rehydrate<br/>backup and reference rules"]
    consumers["data/model/manager/dashboard consumers<br/>dereference accepted artifacts"]

    contracts --> layout --> policy --> consumers
```

## Acceptance

M01 storage changes are acceptable when they:

- preserve canonical M01 artifact names and point-in-time availability;
- define durable layout, reference, retention, restore, and rehydrate expectations before producers depend on them;
- avoid deciding data/model semantics or promoting explainability/diagnostics fields into downstream dependencies;
- avoid committing generated outputs, logs, credentials, or secrets;
- route shared fields, statuses, artifact-reference formats, or storage contract names through `trading-manager/scripts/` before cross-repository dependence.

Current verification:

```bash
git status --short
find docs -maxdepth 1 -type f | sort
find . -maxdepth 2 -type f | sort
git diff --check
```
