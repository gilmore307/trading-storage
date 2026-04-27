# trading-storage

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, SQL output destination contracts, completion receipt storage, references, retention, archive, restore, backup, and rehydrate expectations used by data, strategy, model, execution, dashboard, and manager workflows. Development-stage `trading-data` outputs intentionally stay in local `trading-data/storage/` until these durable contracts are accepted.

It does not own component responsibilities outside that boundary, global contracts, shared registry authority, generated runtime artifacts committed to Git, or secrets.

## Top-Level Structure

```text
docs/        Repository scope, context, workflow, acceptance, task, decisions, and local memory.
```

Source, scripts, tests, and package layout are intentionally not created yet. Add them only after the component contracts, storage expectations, and first implementation slice are explicit. When implementation begins, use `src/` for importable/reusable code, `scripts/` for executable maintenance or operational entrypoints, and `tests/` for first-party tests; `scripts/` may import `src/`, but `src/` must not import `scripts/`.

## Docs Spine

```text
docs/
  00_scope.md
  01_context.md
  02_workflow.md
  03_acceptance.md
  04_task.md
  05_decision.md
  06_memory.md
```

## Platform Dependencies

- `trading-main` owns global contracts, registry, shared helpers, templates, and platform guidance.
- `trading-storage` owns durable storage layout and retention unless this repository is `trading-storage` itself.
- `trading-manager` owns orchestration and lifecycle routing.

Any new global helper, reusable template, shared field, status, type, config key, or vocabulary discovered here must be routed back to `trading-main` before other repositories depend on it.
