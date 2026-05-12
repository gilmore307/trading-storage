# systemd

Reviewed systemd templates for storage-owned helper automation.

## Templates

- `trading-storage-dashboard-read-model-refresh.service` — oneshot refresh of storage-hosted dashboard read models, starting with `historical_task_progress_summary`.
- `trading-storage-dashboard-read-model-refresh.timer` — periodic trigger template for the refresh service; default cadence is 30 seconds for near-real-time public dashboard status.

These templates are not installed or enabled by repository changes. Operator review is required before host-level deployment.
