# Storage Maintenance Playbook

This playbook turns the current storage maintenance queue into per-file-class decisions. It answers four questions for each class:

- what the files are;
- what function they serve;
- who reads them;
- how they may be removed or compacted.

Deletion here means a reviewed lifecycle action. It is not blanket permission to remove bytes without the stated verification gate.

## Decision Rules

- Source data is never removed merely because it is large. It can be compressed or replaced by compact provenance only after the canonical source or SQL coverage gate proves the payload is no longer the only rebuild/audit path.
- Derived read models keep one current file. Repeated full snapshots are not durable evidence.
- Control-plane metadata keeps current state, compact manifests, receipts, and unresolved blocker evidence. Per-request fragments roll off after completion.
- Diagnostic payloads keep compact decisions and repair evidence. Verbose dumps roll off after the decision is represented elsewhere.
- Realtime runtime cycles keep latest/current-window state plus compact metrics. Per-cycle JSON directories are not a permanent data model.
- Trading Economics source payloads under the canonical monthly root are protected. TE duplicate run evidence and old consolidation originals may be compressed, but active TE source facts are not deleted.

## File-Class Decisions

| File class | What it is | Function | Current consumers | Removal or compaction route |
| --- | --- | --- | --- | --- |
| `storage/06_dashboard_cache/read_models/<contract>.json` | Current materialized dashboard read model for one contract. | Serves the dashboard current state without querying every producer. | `trading-dashboard` read-model API, dashboard refresh scripts, `dashboard_system_status`, `dashboard_models`, `dashboard_temporal_explorer`, tests. | Do not delete while the contract is public. It is replaced atomically by refresh. |
| `storage/06_dashboard_cache/schemas/<contract>.schema.json` | Schema placeholder for a dashboard read-model contract. | Validates and documents the current read-model envelope. | Dashboard materializer, artifact index, tests, docs. | Do not delete while the matching current read-model file exists. |
| `storage/06_dashboard_cache/index/dashboard_read_model_index.jsonl` | Legacy materialization index from the snapshot era. | Formerly recorded materialization events and snapshot refs. | No current required consumer. The legacy compactor remains only to clean old rows. | Delete once the file is empty and no legacy snapshot refs remain. Do not recreate it during refresh. |
| `storage/06_dashboard_cache/read_models/<contract>/snapshots/**/*.json` | Old full dashboard read-model snapshots. | Former state-change history for dashboard payloads. | No current required consumer; current dashboard uses `read_models/<contract>.json`. | Delete by dashboard snapshot lifecycle pruning. Keep zero timestamped snapshots unless a debugging grace window is explicitly approved. |
| `storage/06_dashboard_cache/lifecycle/*.json` | Dashboard snapshot prune plans and summaries. | Lifecycle evidence for the latest-only cleanup route. | Storage lifecycle review and tests. | Keep the latest accepted cleanup summary; old dry-run plans may roll off through lifecycle runtime retention. |
| `storage/01_source_data/monthly_backfill/alpaca_bars/<symbol>/<YYYY-MM>/runs/<run>/cleaned/equity_bar.jsonl` | Normalized Alpaca bar source payload for a symbol-month run. | Rebuild/audit source for market bars and SQL ingestion. | Data ingestion lineage, SQL/source coverage checks, potential replay/model rebuilds. | First prove SQL row coverage and source provenance. Then compress by symbol-month or remove duplicate file payload only if compact provenance retains provider, symbol, month, row count, checksum, and receipt refs. |
| `storage/01_source_data/monthly_backfill/alpaca_bars/<symbol>/<YYYY-MM>/runs/<run>/saved/equity_bar.csv` | Saved provider/export form for the same Alpaca bars. | Provider/source evidence and fallback input. | Same as Alpaca JSONL, if SQL/source verification still depends on it. | If JSONL or SQL is canonical and checksums/row counts match, mark the CSV duplicate as compression/removal candidate. Do not keep CSV and JSONL indefinitely for the same rows. |
| `storage/01_source_data/monthly_backfill/alpaca_bars/**/{completion_receipt.json,request_manifest.json,schema.json}` | Small provenance and request evidence for bar source runs. | Records request parameters, schema, and completion state. | Artifact index, lifecycle planner, source audit, possible replay rebuild. | Keep compact provenance. If many near-identical manifests remain, consolidate to symbol-month manifest plus hashes; do not delete the only request/receipt evidence. |
| `storage/02_control_plane/runtime/provider_task_keys/**/task_key.json` and `storage/02_control_plane/runtime/layer_09_option_expression/**/task_key.json` | Per-request provider task-key records, currently especially large for Layer 9 option snapshots. | Correlates individual provider requests during active execution/retry. | Stage executor or repair flow during the active request window. Dashboard/task summaries should consume compact manager state, not every task-key file. | After the provider stage completes, replace with batch manifest keyed by task, month, provider, and request count. Delete or quarantine per-request keys after compact manifest, failure-register disposition, and retry receipts are retained. |
| `storage/02_control_plane/runtime/layer_09_option_expression/gate_review/*.json` | Layer 9 gate-review decision and diagnostic payloads. | Explains provider readiness, policy blocks, repair/retry decisions, and option acquisition gate state. | Task system, repair status, failure register, dashboard blockers. | Keep compact decision, blocker ids, repair ids, retry command refs, and receipt refs. Compress or remove verbose diagnostic arrays after the compact gate-review contract exists. |
| `storage/04_execution_artifacts/runtime/realtime_monitor/<timestamp>/loop_receipt.json` | One realtime monitor loop receipt. | Records runtime monitor loop status. | `dashboard_realtime_signals`, `dashboard_system_status`, alert/diagnostic review. | Keep latest/current window and unresolved-alert evidence. Roll older receipts into compact time-series summary, then TTL delete or compress the old timestamp directory. |
| `storage/04_execution_artifacts/runtime/realtime_monitor/<timestamp>/cycle_*.json` | One realtime monitor cycle payload. | Records per-cycle execution/realtime observation details. | `dashboard_realtime_signals`, `dashboard_system_status`, alert/diagnostic review. | Same as loop receipts: latest/current window plus compact metrics; old cycles are debug sidecars after summary and alert evidence are retained. |
| `storage/02_control_plane/runtime/historical_scheduler_decisions.jsonl` | Append-only scheduler decision log. | Supplies throughput/event-driven scheduler status. | `dashboard_system_status`. | Roll into compact scheduler summary and keep bounded tail. After dashboard reads the summary, old JSONL segments can be archived or deleted by log retention. |
| `storage/02_control_plane/runtime/stage_coverage/*.json` | Stage coverage evidence for historical task progress. | Feeds dashboard task-progress context and stage coverage display. | `dashboard_refresh.latest_stage_coverage_path`, `historical_task_progress_summary`, `dashboard_system_status`. | Keep current/latest coverage and compact historical aggregate. Archive or delete old detailed coverage snapshots after aggregate and task receipts remain. |
| `storage/02_control_plane/runtime/stage_run_dashboard/*.json` | Stage-run dashboard/control-plane derived view. | Exposes stage-run state to system status. | `dashboard_system_status`. | Keep latest/current summary; old detailed snapshots roll off after compact stage-run aggregate exists. |
| `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/YYYY-MM/runs/calendar_maintenance_*_te/` | TE calendar source refresh run. | Canonical TE source payload/update evidence for a month. | TE source audit, `dashboard_system_status` freshness checks, future Layer 10 event-risk promotion. | Do not delete source facts. Audit duplicate refresh semantics first. If repeated runs carry duplicate facts, compact run provenance while preserving canonical source rows and completion receipt evidence. |
| `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/_manifests/source_consolidation_*` | Cold consolidation evidence for old TE source roots moved into the canonical TE boundary. | Proves old monthly/realtime/replay TE roots were consolidated without source loss. | TE lifecycle audit, consolidation review. | Treat as protected cold evidence. Compress/archive it; keep it out of active source scans and Git source exception. Do not delete until a TE-specific review confirms replacement evidence. |
| `storage/02_control_plane/runtime/layer_03_target_state_vector/input_materialization/` | Layer 3 input materialization/debug payloads, including copied bar JSONL. | Helps diagnose and reproduce Layer 3 input construction. | Active Layer 3 run/debug flow; not a permanent dashboard source. | After fold/run closure, prove model lineage references SQL/source refs and compact dataset manifests. Then TTL delete or compress materialized copies unless a model artifact explicitly references them. |
| `storage/01_source_data/layer_09_option_expression/` | Option-expression source payload area. | Current Layer 9 option data source evidence; future shared option source for Layer 3/Layer 9. | Layer 9 data acquisition/replay; planned Layer 3 target-state option features. | Do not create layer-local duplicate stores. Normalize into one shared option source/SQL route with compact provenance; then delete layer-local duplicate copies only after both Layer 3 and Layer 9 consumers read the shared route. |

## Deletion Procedure

Use this sequence for every class except dashboard timestamped snapshots, which already have a reviewed latest-only prune helper.

1. Identify the class and concrete bounded path.
2. Confirm the path is not a protected canonical source, promoted model body, lifecycle receipt, tombstone, active task state, unresolved alert, or lineage-required artifact.
3. Confirm the current consumer has a replacement: current read-model file, compact summary, batch manifest, SQL rows, source receipt, lineage ref, or archive.
4. Build an artifact-index record for the candidate.
5. Build protected-set evidence.
6. For deletion, build quarantine/recheck evidence and wait for the required review gate.
7. Delete only the bounded candidate path or file class.
8. Write a lifecycle receipt or tombstone that records path, byte count, checksum where available, replacement evidence, reviewer/approval ref, and deletion time.

## Immediate Execution Order

1. Dashboard timestamped snapshots: already implemented as latest-only; monitor for regression.
2. Alpaca bars duplicate payloads: build SQL coverage and symbol-month provenance proof before any deletion.
3. Layer 9 task keys: implement compact batch manifests, then delete per-request keys for completed stages.
4. Layer 9 gate reviews: define compact gate-review contract, then compress/remove verbose diagnostic payloads.
5. Realtime monitor cycles: implement latest/current-window plus compact time-series summary.
6. Scheduler/stage dashboard logs: roll up JSONL and snapshots into compact summaries.
7. TE refresh and manifests: audit duplicate TE run semantics; compress cold consolidation evidence.
8. Layer 3 materialization and Layer 9 source duplication: close through lineage and shared option-source contracts.
