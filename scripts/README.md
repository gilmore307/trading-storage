# scripts

Executable storage maintenance and artifact helpers live here. Scripts may import `src/`; `src/` must not import scripts.

## Dashboard helpers

- `dashboard/materialize_read_model.py` validates a dashboard read-model common envelope and writes storage-owned snapshot/latest/schema/index files under `storage/06_dashboard_cache/`.
- `dashboard/refresh_historical_task_progress_read_model.py` runs the manager-owned `historical_task_progress_summary` producer and materializes the validated payload into the accepted storage layout.
- `dashboard/refresh_event_calendar_summary_read_model.py` builds the narrow event calendar summary from accepted SQL event rows and storage-local Trading Economics source evidence.
- `dashboard/refresh_temporal_explorer_summary_read_model.py` builds the primary Timewheel/Temporal Explorer summary from calendar substrate tables and chart cache.
- `dashboard/refresh_realtime_signal_summary_read_model.py` builds the execution-owned realtime signal summary from monitor receipts and materializes the validated payload into the accepted storage layout.
- `dashboard/refresh_execution_runtime_status_read_model.py` builds the execution realtime runtime status read model from the execution-owned readiness artifact for WebSocket clients.
- `dashboard/refresh_public_dashboard_read_models.py` refreshes the public dashboard read-model set, currently including current system status, historical task progress, realtime signal summary, and execution runtime status.

Examples:

```bash
PYTHONPATH=src python3 scripts/dashboard/materialize_read_model.py summary.json \
  --contract-type current_system_status_summary

PYTHONPATH=src python3 scripts/dashboard/refresh_historical_task_progress_read_model.py \
  --trading-manager-root /root/projects/trading-manager \
  --storage-root storage

PYTHONPATH=src python3 scripts/dashboard/refresh_event_calendar_summary_read_model.py \
  --storage-root storage

PYTHONPATH=src python3 scripts/dashboard/refresh_temporal_explorer_summary_read_model.py \
  --storage-root storage

PYTHONPATH=src python3 scripts/dashboard/refresh_realtime_signal_summary_read_model.py \
  --trading-execution-root /root/projects/trading-execution \
  --storage-root storage

PYTHONPATH=src python3 scripts/dashboard/refresh_execution_runtime_status_read_model.py \
  --storage-root storage
```

## Lifecycle helpers

- `lifecycle/maintain_local_storage.py` plans or applies conservative local retention rules for ignored runtime files.

Dry-run:

```bash
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root .
```

Apply after review:

```bash
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root . --apply
```

## Artifact helpers

- `artifacts/store_completion_receipt_payload.py` stores a component completion receipt JSON as a storage-owned `component_completion_receipt_payload` artifact and prints `artifact_ref` metadata.

Example:

```bash
PYTHONPATH=src python3 scripts/artifacts/store_completion_receipt_payload.py receipt.json \
  --request-id mgrreq_backfill_alpaca_bars_2016_01 \
  --run-id run_backfill_alpaca_bars_2016_01_dryrun \
  --producer-repo trading-data \
  --workflow-id 01_feed_alpaca_bars
```
