# systemd

Reviewed systemd templates for storage-owned helper automation.

## Templates

- `trading-storage-dashboard-read-model-refresh.service` — oneshot refresh of storage-hosted dashboard read models, starting with `historical_task_progress_summary`.
- `trading-storage-dashboard-read-model-refresh.timer` — periodic fallback trigger for the refresh service; default cadence is 60 seconds because manager workflow-state events now trigger primary progress refreshes.
- `trading-storage-maintenance.service` — oneshot storage-owned maintenance runner. It applies local retention for storage-owned runtime roots, includes timed log archive/delete behavior, and monitors manager fold states for completed-fold backup candidates.
- `trading-storage-maintenance.timer` — daily fallback trigger for storage maintenance.

`trading-storage-dashboard-read-model-refresh.env.example` documents the reviewed environment knobs (`TRADING_STORAGE_ROOT`, `TRADING_STORAGE_DATA_ROOT`, `TRADING_MANAGER_ROOT`, `TRADING_SECRET_ROOT`, and `TRADING_STORAGE_REFRESH_CADENCE_SECONDS`).

`trading-storage-maintenance.env.example` documents the maintenance root/output knobs for host deployments. The checked-in service template remains pinned to the reviewed local repository path.

These templates are not installed or enabled by repository changes. Operator review is required before host-level deployment.
