# Maintenance Templates

This directory stores operator-reviewed scheduling templates for storage maintenance.

They are templates, not installed services. Installing or enabling one changes host behavior and must be accepted separately.

## Current templates

- `trading-storage-local-retention.service` — runs the local retention helper in apply mode.
- `trading-storage-local-retention.timer` — daily 03:20 America/New_York timer example for the service.

The helper is conservative: it retains `storage/02_control_plane/artifacts/`, archives logs/runs/outputs before removing active copies, and deletes only clearly disposable temporary files or aged local archives.
