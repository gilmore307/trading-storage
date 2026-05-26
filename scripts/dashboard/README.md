# Dashboard Scripts

Executable helpers for storage-hosted dashboard summary/read-model payloads.

- `materialize_read_model.py` validates one dashboard read-model JSON envelope and writes the accepted storage layout: snapshot, `latest.json`, schema, and index row.
- `prune_dashboard_snapshots.py` plans or applies bounded deletion of dashboard read-model snapshot metadata outside the recent-count hot window while preserving `latest.json`, schemas, index rows, Layer 1/2 data, and SQL.
- `refresh_historical_task_progress_read_model.py` runs the manager-owned `historical_task_progress_summary` semantic producer and materializes the validated payload under `storage/06_dashboard_cache/`.
- `refresh_current_system_status_read_model.py` refreshes `current_system_status_summary` from read-only infrastructure observations.
- `refresh_event_calendar_summary_read_model.py` refreshes `event_calendar_summary` from accepted SQL event-calendar rows plus Trading Economics source evidence.
- `refresh_realtime_signal_summary_read_model.py` refreshes `realtime_signal_summary` from execution-owned realtime monitor receipts.
- `refresh_execution_runtime_status_read_model.py` refreshes `execution_realtime_trading_runtime_status` from the execution-owned readiness artifact for WebSocket clients.
- `refresh_public_dashboard_read_models.py` refreshes the current public dashboard read-model set served through `/api/read-models/<contract_type>/latest` and `/ws/read-models/<contract_type>/latest`.

These helpers do not create dashboard UI, provider calls, model activation, broker execution, or account mutation. Refresh helpers may write storage-owned dashboard read-model files only.
