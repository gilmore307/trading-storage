# Dashboard Summary Layout

## Purpose

This document defines the first accepted physical layout and schema-validation boundary for dashboard summary/read-model outputs stored by `trading-storage` and consumed by `trading-dashboard`.

The dashboard remains read-only. These summaries are owner-facing materialized documents, not raw manager/model/data/execution/storage internals.

## Root Layout

Dashboard summaries live under one storage-owned root:

```text
storage/06_dashboard_cache/
```

Accepted subpaths:

```text
storage/06_dashboard_cache/read_models/<contract_type>/latest.json
storage/06_dashboard_cache/read_models/<contract_type>/snapshots/YYYY/MM/DD/<generated_at_utc_compact>.json
storage/06_dashboard_cache/schemas/<contract_type>.schema.json
storage/06_dashboard_cache/index/dashboard_read_model_index.jsonl
```

Where:

- `<contract_type>` is the registered payload value, for example `current_system_status_summary`.
- `<generated_at_utc_compact>` uses UTC compact form `YYYYMMDDTHHMMSSZ` so filenames sort chronologically and avoid punctuation.
- `latest.json` is the newest accepted summary for fast dashboard reads.
- `snapshots/` keeps timestamped state-change history for trend charts and debugging.
- `schemas/` holds JSON Schema contracts for validation once implementation begins.
- `index/dashboard_read_model_index.jsonl` records accepted state-change snapshot paths, checksums, byte counts, freshness, and schema refs per contract.

## Registered Initial Contracts

Accepted implementation targets:

- `current_system_status_summary`
- `historical_task_progress_summary`
- `realtime_signal_summary`
- `execution_realtime_trading_runtime_status`
- `model_layer_readiness_summary`
- `model_promotion_posture_summary`

Parked future contracts:

- `alert_exception_summary`
- `realtime_task_progress_summary`
- `registry_dictionary_profile`
- `runtime_decision_quality_summary`
- `trading_performance_summary`
- `storage_lifecycle_status_summary`

Shared contract names and the layout policy are registered through `trading-manager`. Current public dashboard refreshes use the storage-hosted read-model route `/api/read-models/<contract_type>/latest` for HTTP and `/ws/read-models/<contract_type>/latest` for WebSocket consumers.

## Common Envelope

Every dashboard summary document must use this envelope before contract-specific payload fields:

| Field | Required | Purpose |
|---|---:|---|
| `contract_type` | yes | Registered read-model contract payload value. |
| `schema_version` | yes | Integer schema version for this document contract. |
| `generated_at_utc` | yes | UTC timestamp for materialization freshness. |
| `source_system` | yes | Semantic owner or aggregator that produced the summary. |
| `status` | yes | Owner-facing status value. |
| `severity` | conditional | `critical`, `high`, `medium`, `low`, or `info` where relevant. |
| `summary` | yes | One-sentence owner-facing summary. |
| `chart_payload` | yes | Compact chart-ready object or array; may be empty when no chart applies. |
| `profile_refs` | yes | Registry/profile refs for visible fields; may be empty. |
| `issue_refs` | yes | Alert/exception refs related to this summary; may be empty. |
| `diagnostic_refs` | yes | Issue-focused diagnostic refs only; may be empty. |
| `lineage_refs` | yes | Upstream summary/evidence refs sufficient to understand provenance without exposing raw internals by default. |
| `freshness` | yes | Object describing freshness class, stale threshold, and stale/healthy status. |
| `schema_ref` | yes | Storage path or registry ref for the schema used to validate the document. |

## Writer Responsibility

Storage owns placement, retention, backup, restore, archive, materialized snapshot history, and lifecycle treatment.

Semantic producers remain separate:

| Summary family | Semantic owner |
|---|---|
| Current status, task progress, model promotion posture, alert aggregation | `trading-manager` |
| Model layer readiness, model evidence requirements, and model metrics | `trading-model` |
| Realtime task/signal state and execution connectivity | `trading-execution` |
| Provider/data freshness details | `trading-data` |
| Storage lifecycle/pressure/restore posture | `trading-storage` |
| Registry dictionary/profile explanations | `trading-manager` registry, materialized through storage |

A writer may aggregate multiple owner summaries, but the document must preserve source ownership in `source_system` and `lineage_refs`.

## Validation Boundary

Implementation must validate each summary before `latest.json` is replaced.

Minimum validation requirements:

1. `contract_type` matches the registered contract and directory name.
2. Required common-envelope fields are present.
3. `generated_at_utc` is valid UTC and not in the future beyond accepted clock skew.
4. `schema_ref` resolves to the schema used for validation.
5. `diagnostic_refs` are issue-focused and not a general raw artifact/log/table browser.
6. No secret-like values appear in summary, chart, profile, issue, diagnostic, or lineage payloads.
7. `latest.json` update is atomic after validation succeeds.
8. Timestamped snapshots and index rows are written only when the non-volatile owner-facing state changes.
9. Index row checksum and byte count match the materialized state-change snapshot.

## Lifecycle Posture

Dashboard summaries are small durable owner-facing read models.

Default lifecycle posture:

- retain `latest.json` for every registered summary contract;
- retain the latest few snapshots for trend charts and debugging;
- update `latest.json` without creating a snapshot when only `generated_at_utc` changed;
- prune older snapshots when they fall outside the per-contract hot count window;
- never delete a summary snapshot that is the only remaining explanation for an unresolved alert;
- preserve schema and contract metadata needed for restore compatibility.

The accepted default is count-based retention: keep the latest 10 snapshots per contract. Time-based grace is optional for operational debugging windows, not the default retention mechanism.

## Dashboard Access Rule

`trading-dashboard` may read:

- `latest.json`;
- accepted snapshot history needed for charts;
- schema/profile metadata needed for explanations;
- issue-focused diagnostic refs linked from visible owner-facing problems.

It must not use this layout to create primary views over raw artifacts, raw receipts, raw logs, manager control-plane tables, daemon internals, raw registry rows, or broker/account internals.

## Current Implementation Status

The first storage-side materialization and refresh helpers are implemented:

- `src/trading_storage/dashboard_read_models.py` validates the common dashboard read-model envelope, rejects unsafe contract paths, rejects future timestamps beyond accepted clock skew, scans for secret-like values, atomically replaces `latest.json`, creates the common schema placeholder for the contract, and appends `dashboard_read_model_index.jsonl` rows with checksum and byte counts only for state-change snapshots.
- `scripts/dashboard/materialize_read_model.py` is the executable wrapper for validating and materializing one producer-supplied read-model JSON payload.
- `src/trading_storage/dashboard_refresh.py` and `scripts/dashboard/refresh_historical_task_progress_read_model.py` run the manager-owned `historical_task_progress_summary` producer and materialize the validated output.
- `src/trading_storage/dashboard_realtime_signals.py` and `scripts/dashboard/refresh_realtime_signal_summary_read_model.py` build and materialize `realtime_signal_summary`.
- `src/trading_storage/dashboard_execution_runtime.py` and `scripts/dashboard/refresh_execution_runtime_status_read_model.py` build and materialize `execution_realtime_trading_runtime_status`.
- `src/trading_storage/dashboard_models.py` and `scripts/dashboard/refresh_public_dashboard_read_models.py` build and materialize the Models-page set: `model_layer_readiness_summary` and `model_promotion_posture_summary`.
- `deploy/systemd/trading-storage-dashboard-read-model-refresh.service` and `.timer` provide the reviewed fallback refresh template. Manager workflow-state writes trigger primary progress refreshes; the timer default is 60 seconds for calibration when an event is missed.

Still not implemented: dashboard read adapters, lifecycle timers for dashboard snapshots, or dashboard UI/runtime pages.

### Public refresh batch

`refresh_public_dashboard_read_models.py` refreshes the public dashboard set currently served to `trading-dashboard`:

- `current_system_status_summary` for Status infrastructure/server/API/service/read-model freshness posture;
- `historical_task_progress_summary` for Tasks / Historical Modeling progress;
- `temporal_explorer_summary` for the Timewheel / Temporal Explorer page;
- `realtime_signal_summary` for realtime monitor/signal readiness;
- `execution_realtime_trading_runtime_status` for execution runtime readiness;
- `model_layer_readiness_summary` and `model_promotion_posture_summary` for the Models page.

The systemd refresh service uses this batch entrypoint so public pages update from storage-hosted read models without the dashboard querying raw component internals.
