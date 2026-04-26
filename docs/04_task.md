# Task

## Active Tasks

- None.

## Queued Tasks

- Define the first implementation slice for `trading-storage`.
- Define package/source/test layout after the first implementation slice is accepted.
- Define fixture policy and default test commands.
- Define SQL table/partition contract for `trading-data` historical task outputs.
- Define storage-resident data task completion receipt schema and reference format.
- Identify any global fields, helper surfaces, templates, or type values that must be registered in `trading-main`.

## Open Gaps

- Exact first implementation slice.
- Exact source/package layout.
- Exact fixture and test policy.
- Exact artifact/manifest/ready-signal/request/task-key/completion-receipt contract interactions.
- Exact storage path/reference and SQL destination requirements.

## Recently Accepted

- Recorded storage responsibility for `trading-data` SQL output destinations and durable task completion receipts.
- Created initial `trading-storage` docs spine and repository boundary.
- Added initial `.gitignore` for local environments, generated outputs, logs, and secrets.
