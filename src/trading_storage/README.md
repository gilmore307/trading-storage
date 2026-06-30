# trading_storage Package

Importable storage helper implementation lives here.

## Modules

- `artifact_store.py` owns canonical JSON payload writes and `artifact_ref` metadata generation for storage-owned local artifacts.
- `artifact_index.py` owns conservative filesystem artifact-index scanning and optional JSONL/summary output for lifecycle inventory.
- `dashboard_read_models.py` owns storage-side validation and materialization of dashboard current read-model files plus schemas.
- `dashboard_temporal_explorer.py` owns the storage-side read model for the dashboard Events attention-pool page.
- `dashboard_models.py` owns storage-side model lifecycle and promotion posture read models for the dashboard Models page.
- `dashboard_replay_review.py` owns the storage-side post-replay review projection for Replay Performance, Replay Decisions, Replay Operations, and Events.
- `dashboard_refresh.py` owns storage-side refresh orchestration that runs accepted semantic producers and materializes validated dashboard read models.
- `dashboard_snapshot_lifecycle.py` owns pruning of old dashboard read-model snapshot metadata; it preserves latest summaries, schemas, M01/M02 data, and SQL.
- `file_lifecycle_acceptance.py` owns the one-pass safe file-lifecycle acceptance over current index/protected-set/plan/quarantine/scaffold/compression/dashboard-prune helpers.
- `lifecycle.py` owns local retention planning and application for ignored runtime files, including guards that keep evidence-shaped lifecycle receipts/manifests/tombstones/plans in transient run/output folders until they are extracted to canonical evidence directories.
- `lifecycle_execution_scaffold.py` owns non-mutating compression/archive/restore manifest and receipt drafts for future lifecycle executors.
- `lifecycle_planner.py` owns non-mutating durable-artifact lifecycle planning from artifact-index metadata, protected-set evidence, and reviewed policy rules.
- `protected_set.py` owns conservative protected-set construction from artifact-index records and optional reason-code references/manual pins.
- `quarantine_recheck.py` owns report-only quarantine/recheck evidence for dry-run lifecycle candidates; it never authorizes deletion or mutates storage state.
- `single_file_compression.py` owns the narrow single-file zstd compressed-copy executor and restore verifier for unprotected `compress_candidate` rows; it preserves originals and does not update the artifact index or touch SQL.
- `storage_maintenance.py` owns the scheduled maintenance runner boundary and emits `storage_scheduled_maintenance_summary` receipts.

This package must not import from `scripts/`; executable wrappers belong under `scripts/`.
