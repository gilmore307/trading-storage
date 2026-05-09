# Task

## Active Tasks

- None.

## Queued Tasks

- Identify SQL table/partition candidates for the first durable artifact/manifest/ready-signal implementation.
- Add development-to-durable promotion automation only after manager-side consumers require it.

## Open Gaps

- Exact physical SQL DDL for request, manifest, artifact-ref, and ready-signal persistence.
- Durable object-store backend policy beyond the current filesystem development helper.

## Deferred Until Manager Phase

- Production queue execution and storage-resident lifecycle mutation for request/manifest/artifact/ready-signal records.
- Development-to-durable promotion automation and SQL destination migrations for historical source/feature outputs.
- These implementation details must follow the accepted `manager_request_v1`, `run_manifest_v1`, `artifact_ref_v1`, and `ready_signal_v1` template contracts rather than inventing local-only alternatives.

## Recently Accepted

- Implemented the first storage slice: canonical JSON artifact writes for storage-owned completion receipt payloads under `src/trading_storage/artifact_store.py`, executable helper `scripts/artifacts/store_completion_receipt_payload.py`, and tests under `tests/`.
- Accepted package/source/test layout: `src/` for importable helpers, `scripts/` for executable entrypoints, `tests/` for first-party verification, and ignored local `storage/` for generated artifact payloads.
- Accepted V1 cross-repository handoff template contracts under `main/templates/contracts/`: `manager_request_v1`, `run_manifest_v1`, `artifact_ref_v1`, and `ready_signal_v1`.
- Clarified task-level completion receipt with nested `runs[]` entries for per-run evidence.
- Clarified that completion receipt templates should stay minimal until durable storage consumers require more fields.
- Migrated shared non-code assets from `trading-manager/storage/` to `trading-storage/main/`.
- Linked storage receipt/save planning to `trading-storage/main/templates/data_tasks/` drafts.
- Recorded that data-production development outputs may stay in local ignored staging until accepted; storage responsibility begins with durable SQL destinations and durable task completion receipts once contracts are accepted.
- Created initial `trading-storage` docs spine and repository boundary.
- Added initial `.gitignore` for local environments, generated outputs, logs, and secrets.
