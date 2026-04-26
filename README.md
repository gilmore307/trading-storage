# trading-storage

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, references, retention, archive, restore, backup, and rehydrate expectations used by data, strategy, model, execution, dashboard, and manager workflows.

It does not own component responsibilities outside that boundary, global contracts, shared registry authority, generated runtime artifacts committed to Git, or secrets.

## Top-Level Structure

```text
docs/        Repository scope, context, workflow, acceptance, task, decisions, and local memory.
```

Source, tests, and package layout are intentionally not created yet. They should be added only after the component contracts, storage expectations, and first implementation slice are explicit.

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
