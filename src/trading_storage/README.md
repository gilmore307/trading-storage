# trading_storage Package

Importable storage helper implementation lives here.

## Modules

- `artifact_store.py` owns canonical JSON payload writes and `artifact_ref` metadata generation for storage-owned local artifacts.
- `artifact_index.py` owns conservative filesystem artifact-index scanning and optional JSONL/summary output for lifecycle inventory.
- `dashboard_read_models.py` owns storage-side validation and materialization of dashboard read-model snapshot/latest/schema/index files.
- `dashboard_refresh.py` owns storage-side refresh orchestration that runs accepted semantic producers and materializes validated dashboard read models.
- `lifecycle.py` owns local retention planning and application for ignored runtime files.
- `protected_set.py` owns conservative protected-set construction from artifact-index records and optional reason-code references/manual pins.

This package must not import from `scripts/`; executable wrappers belong under `scripts/`.
