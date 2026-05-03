# Docs

This directory is the authoritative documentation spine for `trading-storage`.

## Files

- `00_scope.md` — repository boundary, in-scope work, out-of-scope work, and owner intent.
- `01_context.md` — why the repository exists, related systems, environment assumptions, and dependencies.
- `02_layer_01_market_regime.md` — Layer 1 storage workflow, artifact boundary, and acceptance gates.
- `03_layer_02_sector_context.md` — Layer 2 storage workflow, artifact boundary, and acceptance gates.
- `80_task.md` — current task state, queued work, blockers, and recently accepted work.
- `81_decision.md` — ratified repository decisions.
- `82_memory.md` — durable local continuity that does not fit narrower docs.

Layer workflow and acceptance live in the numbered layer files. Add future layers as `04_layer_03_...`, `05_layer_04_...`, and so on before adding broad workflow prose.

Do not place generated data, artifacts, notebooks, logs, credentials, or implementation outputs in this directory.
