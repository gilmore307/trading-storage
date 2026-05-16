# trading_storage Package

Importable storage helper implementation lives here.

## Modules

- `artifact_store.py` owns canonical JSON payload writes and `artifact_ref` metadata generation for storage-owned local artifacts.
- `artifact_index.py` owns conservative filesystem artifact-index scanning and optional JSONL/summary output for lifecycle inventory.
- `dashboard_read_models.py` owns storage-side validation and materialization of dashboard read-model snapshot/latest/schema/index files.
- `dashboard_refresh.py` owns storage-side refresh orchestration that runs accepted semantic producers and materializes validated dashboard read models.
- `dashboard_snapshot_lifecycle.py` owns bounded pruning of old dashboard read-model snapshot metadata; it preserves latest summaries, schemas, index files, Layer 1/2 data, and SQL.
- `lifecycle.py` owns local retention planning and application for ignored runtime files.
- `lifecycle_execution_scaffold.py` owns non-mutating compression/archive/restore manifest and receipt drafts for future lifecycle executors.
- `lifecycle_planner.py` owns non-mutating durable-artifact lifecycle planning from artifact-index metadata, protected-set evidence, and reviewed policy rules.
- `protected_set.py` owns conservative protected-set construction from artifact-index records and optional reason-code references/manual pins.
- `quarantine_recheck.py` owns report-only quarantine/recheck evidence for dry-run lifecycle candidates; it never authorizes deletion or mutates storage state.
- `single_file_compression.py` owns the narrow single-file zstd compressed-copy executor for unprotected `compress_candidate` rows; it preserves originals and does not update the artifact index or touch SQL.

This package must not import from `scripts/`; executable wrappers belong under `scripts/`.
