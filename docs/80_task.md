# Task

## Active Tasks

- None.

## Queued Tasks

- None for the current storage-contract-and-lifecycle-helper closeout phase.

## Deferred Beyond Current Closeout

- Physical SQL DDL for durable request/manifest/artifact/ready persistence beyond current manager MVP rows.
- Durable object-store backend selection and production backup/restore infrastructure.
- SQL partitioning and retention policy by source/feature/model output family.
- Development-to-durable promotion automation and SQL destination migrations for historical source/feature/model outputs.
- Production queue execution and storage-resident lifecycle mutation for request/manifest/artifact/ready-signal records.
- Host-level installation/enabling of the local retention systemd timer after operator review.

These implementation details must follow the accepted `manager_request_v1`, `run_manifest_v1`, `artifact_ref_v1`, and `ready_signal_v1` template contracts rather than inventing local-only alternatives. They are component production-phase work, not blockers for this closeout.

## Recently Accepted

- Closed the current storage-contract-and-lifecycle-helper phase in `docs/90_storage_closeout.md`: V1 handoff templates, reusable checked-in non-code assets, local generated-artifact boundary, storage-owned completion receipt payload helper, and local retention/archive/cleanup helper are accepted. No production object store, SQL partitioning, provider call, manager dispatch, model activation, or broker execution is enabled by this closeout.

- Implemented local lifecycle maintenance: `src/trading_storage/lifecycle.py`, `scripts/lifecycle/maintain_local_storage.py`, tests, and systemd timer templates under `main/templates/maintenance/`. The helper dry-runs by default, retains `storage/artifacts/`, archives logs/runs/outputs before removal, deletes old `tmp/`, and prunes local archives after 180 days.
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
