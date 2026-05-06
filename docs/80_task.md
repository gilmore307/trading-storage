# Task

## Active Tasks

- None.

## Queued Tasks

- Define the first implementation slice for `trading-storage`.
- Define package/source/test layout after the first implementation slice is accepted.
- Define fixture policy and default test commands.
- Identify local storage implementation slice candidates that do not force durable cross-repository contracts before the model stack is designed.

## Open Gaps

- Exact first implementation slice.
- Exact source/package layout.
- Exact fixture and test policy.

## Deferred Until Manager Phase

- Promotion criteria from local data-production staging into durable storage contracts.
- SQL table/partition contracts for `trading-data` historical source/feature outputs.
- Storage-resident task-key, request, completion-receipt, artifact, manifest, and ready-signal interactions.
- Development-to-durable promotion, storage path/reference, and SQL destination requirements.
- These durable storage contracts wait until all model layers are designed and `trading-manager` development begins.

## Recently Accepted

- Clarified task-level completion receipt with nested `runs[]` entries for per-run evidence.
- Clarified that completion receipt templates should stay minimal until durable storage consumers require more fields.
- Migrated shared non-code assets from `trading-manager/storage/` to `trading-storage/main/`.
- Linked storage receipt/save planning to `trading-storage/main/templates/data_tasks/` drafts.
- Recorded that data-production development outputs may stay in local ignored staging until accepted; storage responsibility begins with durable SQL destinations and durable task completion receipts once contracts are accepted.
- Created initial `trading-storage` docs spine and repository boundary.
- Added initial `.gitignore` for local environments, generated outputs, logs, and secrets.
