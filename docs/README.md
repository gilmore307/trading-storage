# Docs

This directory is the authoritative documentation spine for `trading-storage`.

## Files

- `00_scope.md` — repository boundary, in-scope work, out-of-scope work, and owner intent.
- `01_context.md` — why the repository exists, related systems, environment assumptions, and dependencies.
- `02_layer_01_market_regime.md` — Layer 1 storage workflow, artifact boundary, and acceptance gates.
- `03_layer_02_sector_context.md` — Layer 2 storage workflow, artifact boundary, and acceptance gates.
- `04_storage_lifecycle.md` — local retention, archive, cleanup, scheduling template, and production boundary.
- `80_task.md` — current task state, queued work, blockers, and recently accepted work.
- `81_decision.md` — ratified repository decisions.
- `82_memory.md` — durable local continuity that does not fit narrower docs.
- `90_storage_closeout.md` — storage-contract-and-lifecycle-helper phase closeout receipt.
- `91_storage_lifecycle_policy.md` — V0.1 lifecycle state machine, retention classes, source/model/SQL policy, and declarative policy shape.
- `92_artifact_index.md` — artifact index and dependency graph design for lifecycle safety.
- `93_protected_set.md` — protected-set rules and quarantine-before-delete policy.
- `94_compression_archive.md` — file compression, SQL archive, summarize-then-archive, and restore-verifier policy.
- `95_lifecycle_receipts.md` — compression/archive/deletion/restore receipt and tombstone contracts.

Layer workflow and acceptance live in the numbered layer files. Existing local helper behavior lives in `04_storage_lifecycle.md`; the production-oriented lifecycle design lives in `91_`-`95_`. Add future layer-specific docs as `05_layer_03_...`, `06_layer_04_...`, and so on before adding broad workflow prose.

Do not place generated data, artifacts, notebooks, logs, credentials, or implementation outputs in this directory.
