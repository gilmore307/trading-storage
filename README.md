# trading-storage

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, SQL output destination contracts, completion receipt storage, references, retention, archive, restore, backup, and rehydrate expectations used by source, derived, model, execution, dashboard, and manager workflows. It also owns checked-in reusable non-code assets migrated from `trading-manager/storage/` under `main/`.

It does not own component responsibilities outside that boundary, global contracts, shared registry authority, generated runtime artifacts committed to Git, or secrets.

## Top-Level Structure

```text
docs/        Repository scope/context, layer storage workflows with acceptance, task/decision/memory.
main/        Checked-in reusable non-code assets shared across trading repositories.
scripts/     Executable storage artifact helpers and maintenance entrypoints.
src/         Importable storage helper package.
tests/       First-party storage tests.
```

The current implementation slices are storage-owned JSON artifact writing for completion receipt payloads and conservative local lifecycle maintenance for ignored runtime files. `src/` owns reusable code, `scripts/` owns executable entrypoints, and `tests/` owns verification; `scripts/` may import `src/`, but `src/` must not import `scripts/`.

## Docs Spine

```text
docs/
  00_scope.md
  01_context.md
  02_layer_01_market_regime.md
  03_layer_02_sector_context.md
  04_storage_lifecycle.md
  80_task.md
  81_decision.md
  82_memory.md
  90_storage_closeout.md
```

Layer-specific `02_`/`03_` docs record retained Layer 1/2 persistence workflows and acceptance gates. `04_storage_lifecycle.md` owns the local retention/archive/cleanup contract. `90_storage_closeout.md` records the current storage-contract-and-lifecycle-helper phase closeout.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src scripts
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root .
```


## Platform Dependencies

- `trading-manager` owns global registry, shared helpers, and platform guidance; reusable non-code assets now live under `trading-storage/main/`.
- `trading-storage` owns durable storage layout and retention policy; the current helper covers local ignored runtime files only.
- `trading-manager` owns control-plane orchestration and lifecycle routing.

Any new global helper, reusable template, shared field, status, type, config key, or vocabulary discovered here must be routed back to `trading-manager` before other repositories depend on it.
