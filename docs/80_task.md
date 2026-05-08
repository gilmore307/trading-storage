# Task

## Active Tasks

- None.

## Queued Tasks

- Define the first implementation slice for `trading-storage` using the accepted V1 handoff contracts.
- Define package/source/test layout after the first implementation slice is accepted.
- Define fixture policy and default test commands.
- Identify SQL table/partition candidates for the first durable artifact/manifest/ready-signal implementation.

## Open Gaps

- Exact first implementation slice.
- Exact source/package layout.
- Exact fixture and test policy.
- Exact physical SQL DDL for request, manifest, artifact-ref, and ready-signal persistence.

## Deferred Until Manager Phase

- Production queue execution and storage-resident lifecycle mutation for request/manifest/artifact/ready-signal records.
- Development-to-durable promotion automation and SQL destination migrations for historical source/feature outputs.
- These implementation details must follow the accepted `manager_request_v1`, `run_manifest_v1`, `artifact_ref_v1`, and `ready_signal_v1` template contracts rather than inventing local-only alternatives.

## Recently Accepted

- Accepted V1 cross-repository handoff template contracts under `main/templates/contracts/`: `manager_request_v1`, `run_manifest_v1`, `artifact_ref_v1`, and `ready_signal_v1`.
- Clarified task-level completion receipt with nested `runs[]` entries for per-run evidence.
- Clarified that completion receipt templates should stay minimal until durable storage consumers require more fields.
- Migrated shared non-code assets from `trading-manager/storage/` to `trading-storage/main/`.
- Linked storage receipt/save planning to `trading-storage/main/templates/data_tasks/` drafts.
- Recorded that data-production development outputs may stay in local ignored staging until accepted; storage responsibility begins with durable SQL destinations and durable task completion receipts once contracts are accepted.
- Created initial `trading-storage` docs spine and repository boundary.
- Added initial `.gitignore` for local environments, generated outputs, logs, and secrets.
