# Tasks

This is the active storage task ledger. Keep lifecycle and dashboard work dry-run-first unless a reviewed slice explicitly authorizes a narrower mutation.

## Active Tasks

- Finish the next storage lifecycle phase in controlled slices. Implemented pieces already cover file-backed SQL archive copies, archive restore verification, no-mutation quarantine/delete receipts, scheduled maintenance inventory, artifact indexing, protected-set evidence, quarantine/recheck evidence, compression/archive/restore scaffolds, narrow single-file compression, file-backed archive copies, latest-only dashboard read models, and one-pass safe file lifecycle acceptance.
- Keep broad/destructive lifecycle execution unauthorized. Current allowed writes are compressed-copy creation for unprotected `compress_candidate` regular files, gzip archive-copy creation for unprotected file-backed `archive_candidate` records, and reviewed bounded dashboard read-model pruning that preserves current read-model files, schemas, SQL, and source data.
- Preserve the no-broker/no-provider boundary: storage helpers must not call providers, activate models, execute broker actions, mutate accounts, detach/drop SQL, move physical quarantine payloads, physically delete source/model/execution/replay evidence, or install/enable host timers without review.
- Maintain storage-hosted dashboard read models for the current public set: `current_system_status_summary`, `historical_task_progress_summary`, `temporal_explorer_summary`, `realtime_signal_summary`, `execution_realtime_trading_runtime_status`, `model_layer_readiness_summary`, and `model_promotion_posture_summary`.

## Current Accepted Surfaces

- Local receipt payload persistence is implemented through `src/trading_storage/artifact_store.py` and `scripts/artifacts/store_completion_receipt_payload.py`.
- Local lifecycle maintenance is implemented through `src/trading_storage/lifecycle.py` and `scripts/lifecycle/maintain_local_storage.py`. The accepted trading runtime route is `storage/90_lifecycle/{tmp,cache,staging,logs,runs,outputs}`; repository-local runtime roots are covered by the same cleanup policy when present.
- Scheduled storage maintenance is implemented through `src/trading_storage/storage_maintenance.py`, `scripts/lifecycle/run_storage_maintenance.py`, and deployable systemd templates under `deploy/systemd/`. Checked-in service/timer files are templates only and are not installed by repository changes.
- Dashboard read-model materialization is implemented through `src/trading_storage/dashboard_read_models.py` and `scripts/dashboard/materialize_read_model.py`.
- Public dashboard refresh orchestration is implemented through `scripts/dashboard/refresh_public_dashboard_read_models.py` plus the contract-specific refresh helpers.
- Lifecycle policy and receipts are documented in `docs/20_storage_lifecycle_policy.md` and `docs/21_lifecycle_receipts.md`.
- Per-file-class storage cleanup decisions are documented in `docs/22_storage_maintenance_playbook.md`.
- Artifact index, protected-set, compression/archive, and dashboard read-model details are owned by `docs/30_artifact_index.md`, `docs/31_protected_set.md`, `docs/32_compression_archive.md`, `docs/40_dashboard_read_models.md`, and `docs/41_dashboard_summary_layout.md`.

## Storage Maintenance Review Queue

These are reviewed maintenance candidates, not deletion authorization. Each cleanup slice still needs artifact-index classification, protected-set evidence, quarantine or recheck evidence, and a receipt unless the item is explicitly a latest-only dashboard cache.

| Priority | Path or file class | Current evidence | Required maintenance action | Status |
| --- | --- | --- | --- | --- |
| P0 | `storage/06_dashboard_cache/**/snapshots/` | Timestamped dashboard snapshots previously grew without bound; cache is now one-file-per-contract and about 296K with zero timestamped snapshots. | Keep `read_models/<contract>.json` and schema only. Scheduled refresh should continue auto-pruning timestamped read-model snapshots. | Verified 2026-06-06: dry-run found zero snapshot records, index had zero rows, empty snapshot directories were removed. Monitor for regression. |
| P0 | `storage/01_source_data/monthly_backfill/alpaca_bars/<symbol>/<YYYY-MM>/` | Operator confirmed bars are retained in SQL. Raw duplicate payload files were 10,724 `equity_bar.jsonl`/`equity_bar.csv` files, about 12.30 GiB. | Keep compact provenance files only: request manifests, schemas, completion receipts, and task keys. Do not regenerate JSONL/CSV payload copies unless SQL rebuild/debug explicitly requires them. | Completed 2026-06-06: deleted JSONL/CSV payload files directly; directory reduced from 13G to 170M; remaining payload-file count is 0. |
| P0 | `storage/02_control_plane/runtime/model_05_option_expression/**/task_key.json` | About 82k task-key files; M05 runtime is about 759M on disk. These are generated control-plane metadata, not durable market source data. | Replace per-request task-key sprawl with compact batch manifests plus accepted receipts. TTL or quarantine old per-request keys after provider tasks complete and gate receipts remain available. | Add lifecycle selector and producer retention metadata. |
| P0 | `storage/02_control_plane/runtime/model_05_option_expression/gate_review/*.json` | One 2016-01 gate review is about 103M. Gate decisions are important evidence but should not become full verbose runtime dumps. | Preserve compact gate decision, blocker, repair, retry, and receipt references. Move verbose diagnostic payloads to bounded debug retention or compression. | Add compact gate-review contract before pruning. |
| P1 | `storage/04_execution_artifacts/runtime/realtime_monitor/<timestamp>/` | About 8,177 timestamped loop directories and 16k JSON files; about 129M by disk usage. | Keep latest/current-window monitor state plus compact time-series summary. TTL or compress old `loop_receipt.json` and `cycle_*.json` after dashboard summaries and alert evidence are retained. | Add rolling retention policy. |
| P1 | `storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl` | Dashboard status uses it as a throughput source; JSONL logs will grow indefinitely. | Add log rollup and compact scheduler-decision summary. Dashboard should read the compact summary for ordinary status. | Add maintenance selector and summary producer. |
| P1 | `storage/02_control_plane/runtime/stage_coverage/` and `storage/02_control_plane/runtime/stage_run_dashboard/` | Derived control-plane/dashboard views; not primary source data. | Keep latest/current summary and bounded historical aggregates, not unlimited detailed snapshots. | Add latest/aggregate retention policy. |
| P1 | `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/YYYY-MM/runs/{calendar_maintenance_*_te,te_recent_calendar_refresh_*}/` | TE source is protected and canonical under monthly backfill, but 2026-06 and 2026-07 refresh runs are accumulating. `te_recent_calendar_refresh_*` is legacy protected TE source evidence, not a disposable temp name. | Preserve TE source facts. Verify refresh runs are incremental/deduplicated and compact repeated run evidence into concise provenance. Do not delete TE source payloads without TE-specific lifecycle review. | Add TE duplicate-run audit. |
| P1 | `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/_manifests/source_consolidation_*` | Cold consolidation evidence is about 59M; `_manifests` is about 244M. | Treat as protected cold evidence, not active source. Add compression/archive coverage and keep it out of active dashboard/Git workflows. | Add cold-evidence compression plan. |
| P2 | `storage/02_control_plane/runtime/layer_03_target_state_vector/input_materialization/` | About 75M. Contains intermediate `bars.jsonl` copies when source and SQL lineage should already identify the input window. | Classify as intermediate materialization/debug sidecar. TTL or compress after fold closure unless referenced by model/dataset lineage. | Add lineage check and retention selector. |
| P2 | `storage/01_source_data/model_05_option_expression/` | Current size is modest, about 85M, but future full option-chain ingestion can dominate storage. | Store shared option source once for Layer 3 and M05 reuse. Keep SQL/canonical source plus compact provenance; avoid layer-local duplicate payload copies. | Coordinate with option-source contract work. |

## Maintenance System Improvements

- Extend scheduled maintenance beyond root inventory and fold-scoped cleanup. It should emit top-N growing paths, file-count hot spots, and known infinite-growth classes.
- Add explicit retention metadata from producers for generated task keys, gate reviews, scheduler decisions, stage coverage views, realtime monitor cycles, and intermediate materialization files.
- Keep source-data exceptions narrow. Trading Economics canonical source remains protected; derived TE runtime/dashboard/control-plane copies should be empty, compact, or explicitly classified as derived.
- Do not let receipts, manifests, dashboards, or task keys become larger than the data they help operate. For each such class, retain one current summary plus bounded evidence needed for audit, retry, or restore.

## Not Current Historical-Training Scope

These items are outside the current no-broker historical-training run and must not be treated as active storage work items:

- production object-store backend selection;
- production lifecycle mutation without artifact index, protected-set, quarantine/recheck, receipt, and reviewed executor coverage;
- development-to-durable promotion automation before a concrete consumer requires it;
- production queue execution and storage-resident lifecycle mutation;
- semantic dashboard summary producers beyond the current public set, dashboard read adapters, or lifecycle timers before a controlled implementation slice is accepted;
- broad movement of every existing local development artifact into storage before concrete paths and acceptance gates exist;
- host-level timer enablement without operator review.
