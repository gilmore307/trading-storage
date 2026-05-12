# Dashboard Summary Layout

## Purpose

This document defines the first accepted physical layout and schema-validation boundary for dashboard summary/read-model outputs stored by `trading-storage` and consumed by `trading-dashboard`.

The dashboard remains read-only. These summaries are owner-facing materialized documents, not raw manager/model/data/execution/storage internals.

## Root Layout

Dashboard summaries live under one storage-owned root:

```text
storage/dashboard/
```

Accepted subpaths:

```text
storage/dashboard/read_models/<contract_type>/latest.json
storage/dashboard/read_models/<contract_type>/snapshots/YYYY/MM/DD/<generated_at_utc_compact>.json
storage/dashboard/schemas/<contract_type>.schema.json
storage/dashboard/index/dashboard_read_model_index.jsonl
```

Where:

- `<contract_type>` is the registered payload value, for example `current_system_status_summary_v1`.
- `<generated_at_utc_compact>` uses UTC compact form `YYYYMMDDTHHMMSSZ` so filenames sort chronologically and avoid punctuation.
- `latest.json` is a copy of the newest accepted snapshot for fast dashboard reads.
- `snapshots/` keeps timestamped materialized history for trend charts and audit.
- `schemas/` holds JSON Schema contracts for validation once implementation begins.
- `index/dashboard_read_model_index.jsonl` records the latest known snapshot path, checksum, byte count, freshness, and schema ref per contract.

## Registered Initial Contracts

Initial implementation targets:

- `current_system_status_summary_v1`
- `alert_exception_summary_v1`
- `historical_task_progress_summary_v1`
- `realtime_task_progress_summary_v1`
- `model_layer_readiness_summary_v1`
- `model_promotion_posture_summary_v1`
- `registry_dictionary_profile_v1`

Parked future contracts:

- `realtime_signal_summary_v1`
- `runtime_decision_quality_summary_v1`
- `trading_performance_summary_v1`
- `storage_lifecycle_status_summary_v1`

Shared contract names and the layout policy are registered in `trading-manager` registry migration `344_register_dashboard_read_model_contracts.sql`. The first refreshable contract is `historical_task_progress_summary_v1`; its semantic producer is manager-owned and its storage refresh wrapper lives in this repository.

## Common Envelope

Every dashboard summary document must use this envelope before contract-specific payload fields:

| Field | Required | Purpose |
|---|---:|---|
| `contract_type` | yes | Registered read-model contract payload value. |
| `contract_version` | yes | Semantic version or integer-compatible version for this document contract. |
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
| Model layer readiness and model metrics | `trading-model` |
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
7. `latest.json` update is atomic after snapshot validation succeeds.
8. Index row checksum and byte count match the materialized snapshot.

## Lifecycle Posture

Dashboard summaries are small durable owner-facing read models.

Default lifecycle posture:

- retain `latest.json` for every registered summary contract;
- retain recent snapshots for trend charts;
- compress/archive older snapshots when trend windows no longer need hot JSON;
- never delete a summary snapshot that is the only remaining explanation for an unresolved alert;
- preserve schema and contract metadata needed for restore compatibility.

Exact TTL values remain future retention-policy details.

## Dashboard Access Rule

`trading-dashboard` may read:

- `latest.json`;
- accepted snapshot history needed for charts;
- schema/profile metadata needed for explanations;
- issue-focused diagnostic refs linked from visible owner-facing problems.

It must not use this layout to create primary views over raw artifacts, raw receipts, raw logs, manager control-plane tables, daemon internals, raw registry rows, or broker/account internals.

## Current Implementation Status

The first storage-side materialization and refresh helpers are implemented:

- `src/trading_storage/dashboard_read_models.py` validates the common dashboard read-model envelope, rejects unsafe contract paths, rejects future timestamps beyond accepted clock skew, scans for secret-like values, writes snapshots, atomically replaces `latest.json`, creates the common schema placeholder for the contract, and appends `dashboard_read_model_index.jsonl` rows with checksum and byte counts.
- `scripts/dashboard/materialize_read_model.py` is the executable wrapper for validating and materializing one producer-supplied read-model JSON payload.
- `src/trading_storage/dashboard_refresh.py` and `scripts/dashboard/refresh_historical_task_progress_read_model.py` run the manager-owned `historical_task_progress_summary_v1` producer and materialize the validated output.
- `deploy/systemd/trading-storage-dashboard-read-model-refresh.service` and `.timer` provide the reviewed periodic-refresh template; the default cadence is 30 seconds for near-real-time public dashboard status, and installing/enabling the timer remains an operator deployment action.

Still not implemented: dashboard read adapters, lifecycle timers for dashboard snapshots, or dashboard UI/runtime pages.
