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

The following dashboard summary families are accepted as storage-bound design targets. Shared contract names are registered through `trading-manager`; the initial file/object layout and validation boundary live in `docs/97_dashboard_summary_layout.md`.

- `current_system_status_summary`;
- `alert_exception_summary`;
- `historical_task_progress_summary`;
- `realtime_task_progress_summary`;
- `model_layer_readiness_summary`;
- `model_promotion_posture_summary`;
- `registry_dictionary_profile`.

Future/parked summary families:

- `realtime_signal_summary`;
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

Dashboard summaries are small, owner-facing read models. They should normally be retained longer than regenerable intermediate artifacts but shorter than permanent promoted model bodies unless a later policy states otherwise.

Default lifecycle posture for future implementation:

- keep latest hot snapshot for every summary family;
- keep recent historical snapshots for trend charts;
- compress/archive older snapshots if they remain useful for dashboard history;
- never delete summaries that are the only remaining explanation for an unresolved alert;
- preserve summary contract/version metadata for restore compatibility.

Exact TTL values remain future retention-policy details; the initial latest/snapshot/schema/index layout is accepted in `docs/97_dashboard_summary_layout.md`.

## Dashboard Access Boundary

The dashboard may read storage-hosted summaries and issue-focused diagnostic refs. It must not use this storage boundary to become:

- a raw artifact browser;
- a receipt browser;
- a global log viewer;
- a control-plane table browser;
- a registry editor;
- a daemon internals explorer.

## Current Status

This document defines the storage-home boundary. `docs/97_dashboard_summary_layout.md` now defines the initial physical JSON layout, common envelope, validation boundary, and first refresh wrapper.

Implemented storage-side support:

- `src/trading_storage/dashboard_read_models.py` validates and materializes producer-supplied read-model JSON payloads into snapshot/latest/schema/index files under `storage/dashboard/`.
- `scripts/dashboard/materialize_read_model.py` exposes the helper as a CLI for one payload at a time.
- `src/trading_storage/dashboard_refresh.py` and `scripts/dashboard/refresh_historical_task_progress_read_model.py` run the manager-owned `historical_task_progress_summary` producer and materialize the validated result.
- `deploy/systemd/trading-storage-dashboard-read-model-refresh.service` and `.timer` define the periodic refresh template; default cadence is 30 seconds for near-real-time public dashboard status, while deployment/enabling remains operator-controlled.
- Tests cover envelope validation, path safety, future timestamp rejection, secret-like payload rejection, snapshot/latest/schema/index writes, the CLI materializer path, and refresh orchestration side-effect flags.

Still not implemented:

- dashboard read adapters;
- lifecycle timers or mutation for dashboard snapshots;
- dashboard UI/runtime pages.

### Current system status producer

`trading_storage.dashboard_system_status` produces `current_system_status_summary` from read-only infrastructure observations: host resources, dashboard API route configuration, systemd service/timer state, dashboard read-model freshness, and refresh cadence. Host resources include CPU usage, memory usage, network download/upload rate, storage capacity, and uptime. The payload also includes a public-facing provider API status list for Alpaca, OKX, and ThetaData. These rows report local configuration/runtime availability only; they must not perform provider calls or expose secret paths/values. Dashboard source-output rows point at the original manager script/task outputs used by the dashboard adapter, such as scheduler state, decision log, workflow state, stage coverage, and stage-run outputs. The materialized dashboard JSON is a sanitized/cache view, not the canonical source file. This contract is for the dashboard Current Status page only; model workflow progress remains in task-specific read models such as `historical_task_progress_summary`.

Refresh entrypoints:

```bash
PYTHONPATH=src python3 scripts/dashboard/refresh_current_system_status_read_model.py --storage-root storage
PYTHONPATH=src python3 scripts/dashboard/refresh_public_dashboard_read_models.py --storage-root storage --trading-manager-root /root/projects/trading-manager
```
