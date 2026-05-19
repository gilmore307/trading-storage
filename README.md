# trading-storage

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, SQL output destination contracts, completion receipt storage, references, retention, archive, restore, backup, and rehydrate expectations used by source, derived, model, execution, dashboard, and manager workflows. It also owns checked-in reusable non-code assets migrated from `trading-manager/storage/` under `main/`.

It does not own component responsibilities outside that boundary, global contracts, shared registry authority, generated runtime artifacts committed to Git, or secrets.

## Top-Level Structure

```text
docs/        Repository scope, context, contracts, tasks, decisions, memory, and storage modules.
main/        Checked-in reusable non-code assets shared across trading repositories.
scripts/     Executable storage artifact helpers and maintenance entrypoints.
src/         Importable storage helper package.
tests/       First-party storage tests.
```

The current implementation slices are storage-owned JSON artifact writing for completion receipt payloads, conservative local lifecycle maintenance for ignored runtime files, scheduled maintenance wrapping, dry-run-first lifecycle planning/protected-set/quarantine evidence, narrow compressed-copy and file-backed archive-copy executors, no-mutation quarantine/delete gate receipts, dashboard read-model materialization, and dashboard read-model refresh wrappers. `src/` owns reusable code, `scripts/` owns executable entrypoints, and `tests/` owns verification; `scripts/` may import `src/`, but `src/` must not import `scripts/`.

## Docs Spine

```text
docs/
  00_scope.md
  01_context.md
  02_architecture.md
  03_contracts.md
  04_task.md
  05_decision.md
  06_memory.md
  10_layer_01_market_regime.md
  11_layer_02_sector_context.md
  20_storage_lifecycle_policy.md
  21_lifecycle_receipts.md
  30_artifact_index.md
  31_protected_set.md
  32_compression_archive.md
  40_dashboard_read_models.md
  41_dashboard_summary_layout.md
```

## Platform Dependencies

- `trading-manager` owns global registry, shared helpers, and platform guidance.
- `trading-storage` owns durable storage layout and retention policy.
- `trading-manager` owns control-plane orchestration and lifecycle routing.

Any new global helper, reusable template, shared field, status, type, config key, or vocabulary discovered here must be routed back to `trading-manager` before other repositories depend on it.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src scripts
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root .
PYTHONPATH=src python3 scripts/lifecycle/run_storage_maintenance.py --root . --json
```
