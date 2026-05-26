# Tasks

This is the active storage task ledger. Keep lifecycle and dashboard work dry-run-first unless a reviewed slice explicitly authorizes a narrower mutation.

## Active Tasks

- Finish the next storage lifecycle phase in controlled slices. Implemented pieces already cover file-backed SQL archive copies, archive restore verification, no-mutation quarantine/delete receipts, scheduled maintenance inventory, artifact indexing, protected-set evidence, quarantine/recheck evidence, compression/archive/restore scaffolds, narrow single-file compression, file-backed archive copies, dashboard snapshot pruning, and one-pass safe file lifecycle acceptance.
- Keep broad/destructive lifecycle execution unauthorized. Current allowed writes are compressed-copy creation for unprotected `compress_candidate` regular files, gzip archive-copy creation for unprotected file-backed `archive_candidate` records, and reviewed bounded dashboard snapshot pruning that preserves `latest.json`, schemas, indexes, SQL, and source data.
- Preserve the no-broker/no-provider boundary: storage helpers must not call providers, activate models, execute broker actions, mutate accounts, detach/drop SQL, move physical quarantine payloads, physically delete source/model/execution/replay evidence, or install/enable host timers without review.
- Maintain storage-hosted dashboard read models for the current public set: `current_system_status_summary`, `historical_task_progress_summary`, `temporal_explorer_summary`, `event_calendar_summary`, `realtime_signal_summary`, and `execution_realtime_trading_runtime_status`.

## Current Accepted Surfaces

- Local receipt payload persistence is implemented through `src/trading_storage/artifact_store.py` and `scripts/artifacts/store_completion_receipt_payload.py`.
- Local lifecycle maintenance is implemented through `src/trading_storage/lifecycle.py` and `scripts/lifecycle/maintain_local_storage.py`. The accepted trading runtime route is `storage/90_lifecycle/{tmp,cache,staging,logs,runs,outputs}`; repository-local runtime roots are covered by the same cleanup policy when present.
- Scheduled storage maintenance is implemented through `src/trading_storage/storage_maintenance.py`, `scripts/lifecycle/run_storage_maintenance.py`, and deployable systemd templates under `deploy/systemd/`. Checked-in service/timer files are templates only and are not installed by repository changes.
- Dashboard read-model materialization is implemented through `src/trading_storage/dashboard_read_models.py` and `scripts/dashboard/materialize_read_model.py`.
- Public dashboard refresh orchestration is implemented through `scripts/dashboard/refresh_public_dashboard_read_models.py` plus the contract-specific refresh helpers.
- Lifecycle policy and receipts are documented in `docs/20_storage_lifecycle_policy.md` and `docs/21_lifecycle_receipts.md`.
- Artifact index, protected-set, compression/archive, and dashboard read-model details are owned by `docs/30_artifact_index.md`, `docs/31_protected_set.md`, `docs/32_compression_archive.md`, `docs/40_dashboard_read_models.md`, and `docs/41_dashboard_summary_layout.md`.

## Not Current Historical-Training Scope

These items are outside the current no-broker historical-training run and must not be treated as active storage work items:

- production object-store backend selection;
- production lifecycle mutation without artifact index, protected-set, quarantine/recheck, receipt, and reviewed executor coverage;
- development-to-durable promotion automation before a concrete consumer requires it;
- production queue execution and storage-resident lifecycle mutation;
- semantic dashboard summary producers beyond the current public set, dashboard read adapters, or lifecycle timers before a controlled implementation slice is accepted;
- broad movement of every existing local development artifact into storage before concrete paths and acceptance gates exist;
- host-level timer enablement without operator review.
