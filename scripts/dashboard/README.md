# Dashboard Scripts

Executable helpers for storage-hosted dashboard summary/read-model payloads.

- `materialize_read_model.py` validates one dashboard read-model JSON envelope and writes the accepted storage layout: snapshot, `latest.json`, schema, and index row.
- `refresh_historical_task_progress_read_model.py` runs the manager-owned `historical_task_progress_summary_v1` semantic producer and materializes the validated payload under `storage/dashboard/`.

These helpers do not create dashboard UI, provider calls, model activation, broker execution, or account mutation. Refresh helpers may write storage-owned dashboard read-model files only.

Additional refresh entrypoints:

- `refresh_current_system_status_read_model.py` — refreshes `current_system_status_summary_v1` from read-only infrastructure observations.
- `refresh_public_dashboard_read_models.py` — refreshes the current public dashboard read-model set used by the website.
