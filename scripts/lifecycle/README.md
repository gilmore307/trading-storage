# Lifecycle Scripts

Executable local storage lifecycle helpers live here.

## Current entrypoints

- `build_artifact_index.py` scans storage-owned filesystem artifacts/read models and emits conservative JSONL inventory metadata according to `docs/30_artifact_index.md`.
- `build_protected_set.py` builds conservative protected-set safety evidence from artifact-index records and optional reason-code references/manual pins according to `docs/31_protected_set.md`.
- `run_file_lifecycle_acceptance.py` runs the complete safe file-lifecycle pass: index, protected set, dry-run plan, quarantine/recheck evidence, execution scaffold, optional compressed-copy creation, and dashboard snapshot prune dry-run.
- `compress_single_file_candidates.py` safely compresses unprotected single-file `compress_candidate` rows to zstd copies, preserving originals and leaving SQL/artifact-index/delete paths untouched according to `docs/32_compression_archive.md`.
- `execute_sql_archive.py` plans or writes reviewed file-backed SQL archive gzip copies for unprotected `archive_candidate` rows. It consumes already-materialized export files only; it does not connect to a database, detach/drop SQL, mutate indexes, quarantine, or delete sources.
- `verify_sql_archive_restore.py` verifies reviewed file-backed SQL archive copies by gzip decompression and checksum comparison without materializing a database restore.
- `build_quarantine_delete_result.py` turns quarantine/recheck evidence into explicit quarantine/deletion/tombstone draft receipts while preserving the current no-mutation boundary.
- `run_storage_maintenance.py` runs the scheduled maintenance wrapper for storage-owned timed cleanup phases, monitors completed manager folds when `--manager-root` is provided, and writes `storage_scheduled_maintenance_summary`.
- `maintain_local_storage.py` plans or applies conservative cleanup for ignored runtime files according to `docs/20_storage_lifecycle_policy.md`.
- `plan_storage_lifecycle.py` emits non-mutating durable-artifact lifecycle plans from artifact-index/protected-set/policy evidence according to `docs/20_storage_lifecycle_policy.md`.
- `build_lifecycle_execution_scaffold.py` emits non-mutating compression/archive/restore manifest and receipt drafts from lifecycle plans according to `docs/32_compression_archive.md` and `docs/21_lifecycle_receipts.md`.
- `build_quarantine_recheck_evidence.py` emits report-only quarantine/recheck gate evidence from lifecycle plans and optional final protected-set evidence according to `docs/31_protected_set.md`.

Scripts in this directory may import `src/trading_storage`; reusable lifecycle logic belongs in `src/`, not here.
