# Task

## Active Tasks

- None.

## Queued Tasks

- Define the first implementation slice for `trading-storage`.
- Define package/source/test layout after the first implementation slice is accepted.
- Define fixture policy and default test commands.
- Define promotion criteria from local data-production staging files into durable storage contracts.
- Define SQL table/partition contract for `trading-data` historical source/feature outputs after development mode.
- Define storage-resident data task completion receipt schema and reference format.
- Align durable receipt and save contract work with `trading-storage/main/templates/data_tasks/completion_receipt.json` and `save_spec.md`.
- Identify any global fields, helper surfaces, templates, or type values that must be registered in `trading-main`.

## Open Gaps

- Exact first implementation slice.
- Exact source/package layout.
- Exact fixture and test policy.
- Exact artifact/manifest/ready-signal/request/task-key/completion-receipt contract interactions.
- Exact development-to-durable promotion, storage path/reference, and SQL destination requirements.

## Recently Accepted

- Clarified task-level completion receipt with nested `runs[]` entries for per-run evidence.
- Clarified that completion receipt templates should stay minimal until durable storage consumers require more fields.
- Migrated shared non-code assets from `trading-main/storage/` to `trading-storage/main/`.
- Linked storage receipt/save planning to `trading-storage/main/templates/data_tasks/` drafts.
- Recorded that data-production development outputs may stay in local ignored staging until accepted; storage responsibility begins with durable SQL destinations and durable task completion receipts once contracts are accepted.
- Created initial `trading-storage` docs spine and repository boundary.
- Added initial `.gitignore` for local environments, generated outputs, logs, and secrets.
