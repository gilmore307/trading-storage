# trading-storage

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, SQL output destination contracts, completion receipt storage, references, retention, archive, restore, backup, and rehydrate expectations used by source, derived, model, execution, dashboard, and manager workflows. It also owns checked-in reusable non-code assets migrated from `trading-manager/storage/` under `main/`.

It does not own component responsibilities outside that boundary, global contracts, shared registry authority, generated runtime artifacts committed to Git, or secrets.

## Top-Level Structure

```text
docs/        Repository scope/context, layer storage workflows with acceptance, task/decision/memory.
main/        Checked-in reusable non-code assets shared across trading repositories.
```

Source, scripts, tests, and package layout are intentionally not created yet. Add them only after the component contracts, storage expectations, and first implementation slice are explicit. When implementation begins, use `src/` for importable/reusable code, `scripts/` for executable maintenance or operational entrypoints, and `tests/` for first-party tests; `scripts/` may import `src/`, but `src/` must not import `scripts/`.

## Docs Spine

```text
docs/
  00_scope.md
  01_context.md
  02_layer_01_market_regime.md
  03_layer_02_sector_context.md
  80_task.md
  81_decision.md
  82_memory.md
```

Layer-specific `02_`/`03_` docs record active persistence workflows, boundaries, and acceptance gates for Layer 1 and Layer 2.

## Platform Dependencies

- `trading-manager` owns global registry, shared helpers, and platform guidance; reusable non-code assets now live under `trading-storage/main/`.
- `trading-storage` owns durable storage layout and retention unless this repository is `trading-storage` itself.
- `trading-manager` owns control-plane orchestration and lifecycle routing.

Any new global helper, reusable template, shared field, status, type, config key, or vocabulary discovered here must be routed back to `trading-manager` before other repositories depend on it.
