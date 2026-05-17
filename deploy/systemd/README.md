# systemd

Reviewed systemd templates for storage-owned helper automation.

## Templates

- `trading-storage-dashboard-read-model-refresh.service` — oneshot refresh of storage-hosted dashboard read models, starting with `historical_task_progress_summary`.
- `trading-storage-dashboard-read-model-refresh.timer` — periodic trigger template for the refresh service; default cadence is 5 seconds for near-real-time public dashboard status.

`trading-storage-dashboard-read-model-refresh.env.example` documents the reviewed environment knobs (`TRADING_STORAGE_ROOT`, `TRADING_STORAGE_DATA_ROOT`, `TRADING_MANAGER_ROOT`, `TRADING_SECRET_ROOT`, and `TRADING_STORAGE_REFRESH_CADENCE_SECONDS`).

These templates are not installed or enabled by repository changes. Operator review is required before host-level deployment.
