# trading_storage Package

Importable storage helper implementation lives here.

## Modules

- `artifact_store.py` owns canonical JSON payload writes and `artifact_ref_v1` metadata generation for storage-owned local artifacts.
- `dashboard_read_models.py` owns storage-side validation and materialization of dashboard read-model snapshot/latest/schema/index files.
- `dashboard_refresh.py` owns storage-side refresh orchestration that runs accepted semantic producers and materializes validated dashboard read models.
- `lifecycle.py` owns local retention planning and application for ignored runtime files.

This package must not import from `scripts/`; executable wrappers belong under `scripts/`.
