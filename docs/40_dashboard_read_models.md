# Dashboard Read-Model Storage

## Purpose

`trading-storage` is the durable/materialized home for dashboard summary/read-model outputs consumed by `trading-dashboard`. This is a specific instance of the broader rule that durable system-owned non-SQL saved data belongs in storage.

The dashboard is owner-facing and read-only. It should read compact summary outputs from storage instead of assembling pages directly from raw manager, model, data, execution, registry, daemon, receipt, or artifact internals.

## Ownership Boundary

Storage owns:

- durable location and layout for dashboard read-model outputs;
- retention, backup, restore, archive, and lifecycle policy for those outputs;
- materialized snapshot/version storage;
- refresh wrappers that run accepted semantic producers and write validated storage-owned dashboard snapshots;
- profile/read freshness metadata needed by the dashboard;
- storage lifecycle health summaries exposed to the dashboard.

Storage does not own:

- source semantics of model metrics, provider state, execution state, alerts, or task progress;
- semantic interpretation or generation of component-owned summaries;
- model promotion decisions;
- provider calls;
- broker execution;
- dashboard UI rendering;
- registry governance.

The semantic owner of each summary remains the component that understands the data. For example, `trading-manager` owns task/scheduler/promotion summary semantics; `trading-model` owns model metric semantics; `trading-execution` owns realtime/execution summary semantics; `trading-storage` owns persistence and lifecycle posture.

## Flow

```text
component evidence -> semantic owner aggregation -> storage materialized summary -> dashboard read-only presentation
```

`trading-dashboard` reads the materialized summary from storage. It should not query raw internal component tables as primary page inputs.

## Initial Dashboard Summary Families

The following dashboard summary families are accepted as storage-bound design targets. Shared contract names are registered through `trading-manager`; the initial file/object layout and validation boundary live in `docs/41_dashboard_summary_layout.md`.

- `current_system_status_summary`;
- `alert_exception_summary`;
- `historical_task_progress_summary`;
- `realtime_task_progress_summary`;
- `model_layer_readiness_summary`;
- `model_promotion_posture_summary`;
- `registry_dictionary_profile`.

Implemented realtime summary families:

- `temporal_explorer_summary`;
- `event_calendar_summary`;
- `execution_realtime_trading_runtime_status`;
- `realtime_signal_summary`;

Future/parked summary families:

- `runtime_decision_quality_summary`;
- `trading_performance_summary`;
- `storage_lifecycle_status_summary`.

## Storage Shape Principles

Dashboard summaries should be:

- compact enough for quick page loads;
- identified by stable contract type and versioned by `schema_version`;
- timestamped with generation freshness;
- reproducible from upstream evidence where practical;
- traceable to diagnostic evidence refs without exposing raw internals by default;
- lifecycle-managed separately from large intermediate artifacts;
- safe to cache/read without secrets.

A summary row or document should generally include:

- `contract_type`;
- `generated_at_utc`;
- `source_system`;
- owner-facing `status`;
- optional `severity`;
- human-readable `summary`;
- compact chart-ready payload;
- registry/profile refs for visible fields;
- alert/issue refs;
- diagnostic refs for issue-focused drilldowns only.

## Storage Lifecycle Treatment

Dashboard summaries are owner-facing metadata caches. They are not canonical Layer 1/2 data and should not consume unbounded storage.

Default lifecycle posture:

- keep `latest.json` hot for every summary family;
- keep schemas and compact index metadata;
- keep a short recent snapshot window for charts/debugging;
- prune high-frequency snapshots by count after the model-run cycle closes;
- never delete summaries that are the only remaining explanation for an unresolved alert;
- preserve summary contract/version metadata for restore compatibility;
- never use dashboard snapshot pruning to delete Layer 1/2 data, SQL data, schemas, index files, or `latest.json`.

The current V0.1 snapshot-prune helper defaults to keeping the latest 10 snapshots per contract and marking older snapshots as delete candidates. The optional `--max-age-hours` flag can add a temporary age grace window, but the default is count-only. It is dry-run by default and requires `--apply` plus a reviewed approval reference for deletion.

Operational hold: do not apply dashboard snapshot deletion while the event model is being redesigned and downstream models must be regenerated. These metadata snapshots may still be needed for comparison, debugging, and regeneration evidence until that cycle is closed and reviewed.

## Dashboard Access Boundary

The dashboard may read storage-hosted summaries and issue-focused diagnostic refs. It must not use this storage boundary to become:

- a raw artifact browser;
- a receipt browser;
- a global log viewer;
- a control-plane table browser;
- a registry editor;
- a daemon internals explorer.

## Current Status

This document defines the storage-home boundary. `docs/41_dashboard_summary_layout.md` now defines the initial physical JSON layout, common envelope, validation boundary, and first refresh wrapper.

Implemented storage-side support:

- `src/trading_storage/dashboard_read_models.py` validates and materializes producer-supplied read-model JSON payloads into snapshot/latest/schema/index files under `storage/06_dashboard_cache/`.
- `src/trading_storage/dashboard_snapshot_lifecycle.py` and `scripts/dashboard/prune_dashboard_snapshots.py` plan or apply bounded deletion for old dashboard snapshot metadata while preserving `latest.json`, schemas, index files, Layer 1/2 data, and SQL.
- `scripts/dashboard/materialize_read_model.py` exposes the helper as a CLI for one payload at a time.
- `src/trading_storage/dashboard_refresh.py` and `scripts/dashboard/refresh_historical_task_progress_read_model.py` run the manager-owned `historical_task_progress_summary` producer and materialize the validated result; when no explicit coverage path is supplied, the refresh wrapper attaches the newest manager stage-coverage artifact so the Historical Task Progress page can show coverage instead of a blank placeholder.
- `src/trading_storage/dashboard_temporal_explorer.py` and `scripts/dashboard/refresh_temporal_explorer_summary_read_model.py` build and materialize `temporal_explorer_summary` for the dashboard Timewheel page from `calendar_day`, `calendar_market_session`, `calendar_scheduled_event`, `calendar_event_result`, `calendar_news_event_index`, and `chart_ohlcv_cache`. This is the primary calendar/dashboard route.
- `src/trading_storage/dashboard_event_calendar.py` and `scripts/dashboard/refresh_event_calendar_summary_read_model.py` build and materialize the narrow support read model `event_calendar_summary` from accepted SQL event rows plus storage-hosted Trading Economics refresh evidence.
- `src/trading_storage/dashboard_execution_runtime.py` and `scripts/dashboard/refresh_execution_runtime_status_read_model.py` build and materialize `execution_realtime_trading_runtime_status` from the execution-owned readiness artifact. Dashboard clients consume it through `/ws/read-models/execution_realtime_trading_runtime_status/latest`.
- `src/trading_storage/dashboard_realtime_signals.py` and `scripts/dashboard/refresh_realtime_signal_summary_read_model.py` build and materialize `realtime_signal_summary` from execution-owned realtime monitor receipts. When no realtime monitor receipt exists, the producer emits an explicit safe `not_started` state rather than fabricating signal metrics.
- `deploy/systemd/trading-storage-dashboard-read-model-refresh.service` and `.timer` define the fallback periodic refresh template. Manager workflow-state writes trigger primary progress refreshes, while the timer default is 60 seconds for calibration when an event is missed.
- Tests cover envelope validation, path safety, future timestamp rejection, secret-like payload rejection, snapshot/latest/schema/index writes, the CLI materializer path, and refresh orchestration side-effect flags.

Still not implemented:

- dashboard read adapters;
- lifecycle timers or mutation for dashboard snapshots;
- dashboard UI/runtime pages.

### Current system status producer

`trading_storage.dashboard_system_status` produces `current_system_status_summary` from read-only infrastructure observations: host resources, scheduler runtime throughput, subordinate provider parallelism parameters, dashboard source-connection route configuration, all installed `trading-*` systemd unit-file states, dashboard read-model freshness, and refresh cadence. Host resources include CPU usage, memory usage, network download/upload rate, storage capacity, and uptime. Scheduler runtime throughput is exposed as a compact owner-facing status object built from the manager decision log: 3 month-ingest + 1 model-worker topology, six-month fold cadence, completion rate, peak completion burst, observation window, and idle/blocked decision count. Scheduler parallelism remains available as subordinate provider-dispatch/resource-gate detail with selected/max provider workers, request batch limit, drain/refresh posture, load target, and memory budget; it is calculated from local config plus current load/memory and performs no dispatch. The payload also includes public-facing source-connection status rows for Alpaca, OKX, ThetaData, and the Trading Economics recent-calendar source path, including its schedule and worker unit status. These rows report local configuration/runtime availability only; they must not perform provider calls or expose secret paths/values. Dashboard source-output rows point at original component artifacts used by dashboard read models across manager, execution, data, and storage: scheduler state, decision logs, active workflow state, stage coverage/run outputs, execution runtime status, realtime monitor receipts/cycles, Trading Economics calendar receipts/files, dashboard read-model latest files, and the dashboard read-model index. Each source-output row declares a freshness class: `heartbeat` artifacts are expected to update on a service/timer heartbeat, while `event_driven` artifacts update only when a decision, stage-progress event, runtime check, or bounded refresh output exists. The active workflow row resolves the active month-specific workflow state from scheduler state; when scheduler state is unavailable, it uses the latest month-specific workflow-state file. When future website/read-model slices add more original source outputs, this inventory must be updated in the same slice so source freshness remains complete and auditable. The materialized dashboard JSON is a sanitized/cache view, not the canonical source file. This contract is for the dashboard Status page only; model workflow progress remains in task-specific read models such as `historical_task_progress_summary`.

Refresh entrypoints:

```bash
PYTHONPATH=src python3 scripts/dashboard/refresh_current_system_status_read_model.py --storage-root storage
PYTHONPATH=src python3 scripts/dashboard/refresh_event_calendar_summary_read_model.py --storage-root storage
PYTHONPATH=src python3 scripts/dashboard/refresh_temporal_explorer_summary_read_model.py --storage-root storage
PYTHONPATH=src python3 scripts/dashboard/refresh_execution_runtime_status_read_model.py --storage-root storage
PYTHONPATH=src python3 scripts/dashboard/refresh_realtime_signal_summary_read_model.py --storage-root storage --trading-execution-root /root/projects/trading-execution
PYTHONPATH=src python3 scripts/dashboard/refresh_public_dashboard_read_models.py --storage-root storage --trading-manager-root /root/projects/trading-manager --trading-execution-root /root/projects/trading-execution
```

### Event calendar producer

`trading_storage.dashboard_temporal_explorer` produces `temporal_explorer_summary` for the dashboard Timewheel page. It reads the accepted calendar substrate tables, chart cache, execution runtime status, and replay artifact root, emits a centered viewport, 21 synchronized time ticks for the chart x-axis, visible event markers, event/status lanes, chart-cache bars when present, and explicit empty/not-populated states for unpopulated sources. Market-state summary belongs to Status, not a Timewheel lane. It performs no provider calls, SQL mutation, model activation, broker execution, or account mutation.

`trading_storage.dashboard_event_calendar` remains a narrow support producer for `event_calendar_summary`. It reads `trading_data.source_10_event_risk_governor` rows inside a recent/upcoming window and storage-local Trading Economics source receipts under the canonical append-only root `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/`.

### Execution runtime status producer

`trading_storage.dashboard_execution_runtime` produces `execution_realtime_trading_runtime_status` from the execution-owned runtime readiness artifact at `storage/04_execution_artifacts/runtime/realtime_trading_runtime/runtime_status.json`. It exposes the active model pointer state, next gate, connected interfaces, allowed action flags, required runtime inputs, and safety counters in the common dashboard envelope. It performs no provider calls, model activation, order construction, broker execution, or account mutation. The dashboard WebSocket route is:

```text
/ws/read-models/execution_realtime_trading_runtime_status/latest
```

### Realtime signal producer

`trading_storage.dashboard_realtime_signals` produces `realtime_signal_summary` from read-only execution monitor evidence. It summarizes monitor state, cycle counts, provider-observation counts, shadow decision-input readiness, visible gaps, and safety-boundary flags. It performs no provider calls, broker/account mutation, order mutation, or model activation. If execution has not written realtime monitor receipts yet, the summary remains `not_started` with explicit zero counts and safe empty readiness cards.
