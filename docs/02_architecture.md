# Architecture

## Module Map

| Docs band | Implementation surface | Purpose |
|---|---|---|
| `10_*` | layer-specific storage docs | Storage boundaries for model/data layer artifacts. |
| `20_*` | `scripts/lifecycle/` | Storage lifecycle policy and lifecycle receipts. |
| `30_*` | `scripts/artifacts/`, storage artifact layouts | Artifact index, protected set, compression, and archive rules. |
| `40_*` | `scripts/dashboard/` | Dashboard read models and summary layouts. |

## Purpose

This file defines the current local storage lifecycle helper for `trading-storage`: what is kept, what is archived, what is deleted, and what remains deferred until production storage is accepted. It also records the accepted direction that trading runtime disposable cache/tmp/local staging should live under storage-owned ignored roots and be cleaned by storage-owned scheduled maintenance.

The goal is simple: source-controlled files stay clean, durable evidence is explicit, disposable local files cannot quietly become the system of record, and trading runtime scratch space is cleaned through one storage-owned policy instead of scattered component-specific conventions.

The storage lifecycle design lives in the current module files:

- `20_storage_lifecycle_policy.md`
- `21_lifecycle_receipts.md`
- `30_artifact_index.md`
- `31_protected_set.md`
- `32_compression_archive.md`

This file maps those modules and records the implemented local ignored-file helper contract.

## Storage Classes

| Class | Path | Owner | Rule |
|---|---|---|---|
| Source-controlled contracts/assets | `docs/`, `main/`, `src/`, `scripts/`, `tests/` | Git | Reviewed and committed. No generated output belongs here. |
| Source data and source outputs | `storage/01_source_data/` | data-producing repositories with storage-owned placement | Reusable Layer 1/2 foundations, downloaded/provider/source evidence, monthly backfill data, realtime source evidence, source-output artifacts, event evidence, and explicitly fold-scoped target/source folders. Reusable Layer 1/2 data is not deleted; fold-scoped target/source folders may become deletion candidates only after the full fold closes. |
| Control-plane state | `storage/02_control_plane/` | `trading-manager` with storage-owned placement | Manager task payloads, scheduler state, locks, coverage, dispatch receipts, and workflow checkpoints. |
| Model artifacts | `storage/03_model_artifacts/` | `trading-model` with storage-owned placement | Model research artifacts, training/runtime outputs, diagnostics, and promotion-adjacent model evidence. |
| Execution artifacts | `storage/04_execution_artifacts/` | `trading-execution` with storage-owned placement | Realtime monitor receipts, execution-side observations, shadow/live evidence, and execution runtime files. |
| Benchmark datasets | `storage/05_benchmark_datasets/` | `trading-evaluation` with storage-owned placement | Frozen benchmark preparation bundles, replay dataset manifests, acquisition plans, and benchmark data snapshots. |
| Dashboard cache | `storage/06_dashboard_cache/` | `trading-storage` dashboard read-model helpers | Materialized latest/snapshot/schema/index JSON used by dashboard readers; cache retention is storage-owned. |
| Local durable artifact evidence | `storage/02_control_plane/artifacts/` | `trading-storage` helper | Retained until reviewed promotion/deletion policy supersedes it. Not committed. |
| Local archive | `storage/90_lifecycle/archive/` | retention helper | Receives aged logs/runs/outputs before active copies are removed. Pruned after 180 days. Not committed. |
| Current temporary scratch | `tmp/` | current local helper | Deleted after 3 days. Not archived. Transitional root. |
| Current local logs | `logs/` | current local helper | Archived after 14 days, then active copy is removed. Transitional root. |
| Current local run staging | `runs/` | current local helper | Archived after 30 days, then active copy is removed. Transitional root. |
| Current local development outputs | `outputs/` | current local helper | Archived after 30 days, then active copy is removed. Transitional root. |
| Target temporary scratch | `storage/90_lifecycle/tmp/` | `trading-storage` lifecycle helper | Deleted after 3 days. Not archived. |
| Target local logs | `storage/90_lifecycle/logs/` | `trading-storage` lifecycle helper | Archived after 14 days, then active copy is removed. |
| Target local run staging | `storage/90_lifecycle/runs/` | `trading-storage` lifecycle helper | Archived after 30 days, then active copy is removed. |
| Target local development outputs | `storage/90_lifecycle/outputs/` | `trading-storage` lifecycle helper | Archived after 30 days, then active copy is removed. |
| Cross-component disposable staging | `storage/90_lifecycle/staging/<component>/` | `trading-storage` lifecycle helper | Archived after 30 days, then active copy is removed. |
| Cross-component disposable cache | `storage/90_lifecycle/cache/<component>/` | `trading-storage` lifecycle helper | Deleted after 3 days. Not durable evidence. |
| Python/test caches | `__pycache__/`, `.pytest_cache/`, similar | tools | Deleted by the lifecycle helper where covered; regenerated by tools. |

All runtime classes above are ignored by Git. Existing component-local `tmp/`, `runs/`, `outputs/`, or cache paths are covered compatibility roots; new trading runtime staging should target storage-owned ignored roots.

## Maintenance Helper

The lifecycle implementation lives in:

```text
src/trading_storage/lifecycle.py
scripts/lifecycle/maintain_local_storage.py
```

Dry-run first:

```bash
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root .
```

Apply reviewed local cleanup:

```bash
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root . --apply
```

The command emits a JSON plan with counts for `archive`, `delete`, `retain`, and `skip` actions.

## Safety Rules

- Dry-run is the default.
- Durable numbered roots are report-only by default in local retention; the helper does not delete source data, control-plane evidence, model artifacts, execution artifacts, benchmark datasets, completion receipts, or other storage-owned artifact evidence. Artifact-index lifecycle planning may still classify disposable Layer 1/2 runtime/log/intermediate files as TTL cleanup candidates after run/fold close.
- `storage/01_source_data/fold_scoped/<fold_id>/` is the only accepted source-data folder boundary for fold-completion cleanup candidates. Scheduled maintenance may report those folders after a completed ten-layer fold, but real deletion still requires artifact-index coverage, protected-set clearance, quarantine/recheck, and a deletion receipt.
- Current compatibility `logs/`, `runs/`, and `outputs/` are copied to `storage/90_lifecycle/archive/` before active files are removed.
- Current compatibility `tmp/` is disposable and is deleted after its TTL without archiving.
- Target `storage/90_lifecycle/logs/`, `storage/90_lifecycle/runs/`, `storage/90_lifecycle/outputs/`, `storage/90_lifecycle/tmp/`, `storage/90_lifecycle/staging/<component>/`, and `storage/90_lifecycle/cache/<component>/` roots are covered by the lifecycle helper.
- Trading runtime scratch/staging/cache paths should be under storage-owned ignored roots so scheduled cleanup covers them uniformly.
- Python/test caches are disposable and may be removed on every cleanup run; they are tool byproducts, not accepted trading runtime staging.
- Symlinks are skipped.
- Archive destinations must stay under the repository root.
- The helper does not call providers, mutate manager SQL, activate models, execute trades, or change broker/account state.

## Scheduling

Timer templates live under:

```text
main/templates/maintenance/
```

They are not installed by this repository commit. Installing or enabling them changes host behavior and must be accepted separately.

The accepted default cadence is daily local retention after market/data work is quiet:

```text
03:20 America/New_York
```

The timer should run the helper with `--apply` only after the dry-run output has been reviewed at least once on the target host. The target shape is one storage-owned scheduled cleanup path for durable-adjacent runtime scratch, staging, cache, logs, runs, and outputs.

## Production Boundary

This lifecycle helper is a local development/operations hygiene mechanism. It does not replace future production storage design.

Still deferred until a concrete production consumer requires them:

- object-store backend selection;
- SQL partitioning and retention by output family;
- backup/restore/archive infrastructure beyond local filesystem archives;
- development-to-durable promotion automation;
- storage-resident lifecycle mutation coordinated with manager state.
