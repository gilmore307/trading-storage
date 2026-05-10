# trading_storage Package

Importable storage helper implementation lives here.

## Modules

- `artifact_store.py` owns canonical JSON payload writes and `artifact_ref_v1` metadata generation for storage-owned local artifacts.
- `lifecycle.py` owns local retention planning and application for ignored runtime files.

This package must not import from `scripts/`; executable wrappers belong under `scripts/`.
