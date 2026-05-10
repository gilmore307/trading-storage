# Task

## Active Tasks

- Implement the next storage lifecycle phase in controlled slices: artifact index, protected-set builder, dry-run lifecycle planner, file compression executor, SQL archive executor, restore verifier, and finally a daemon/scheduled maintenance wrapper.
- Keep lifecycle execution dry-run-only until artifact index, protected-set checks, quarantine-before-delete, and lifecycle receipts are implemented and reviewed.

The initial storage-contract-and-lifecycle-helper phase is closed. Current historical training can use local receipt payload persistence, artifact refs, manager summary rows, and dry-run-first local lifecycle maintenance. The new V0.1 lifecycle policy is accepted as the next shape but does not authorize production deletion, SQL detach/drop, or daemon execution yet.

## Historical-Training Todo Status

- Local generated artifacts remain ignored and storage-owned.
- Completion receipt payload storage is implemented through `src/trading_storage/artifact_store.py` and `scripts/artifacts/store_completion_receipt_payload.py`.
- Local lifecycle maintenance is implemented through `src/trading_storage/lifecycle.py` and `scripts/lifecycle/maintain_local_storage.py`.
- Maintenance systemd templates are checked in but intentionally not installed or enabled.
- V0.1 lifecycle design is documented in `docs/91_storage_lifecycle_policy.md` through `docs/95_lifecycle_receipts.md`: promoted model bodies are kept permanently, regenerable intermediate data may expire by TTL, source data is compressed before deletion unless disposable, SQL detail is archived through export/restore workflows, all lifecycle actions require manifest/receipt evidence, and normal lifecycle maintenance enters through manager's unified request/task-summary surface before storage executes physical actions.

## Not Current Historical-Training Scope

These items are intentionally outside the current no-broker historical-training run and must not be treated as active storage work items:

- production object-store backend selection;
- production lifecycle mutation before artifact index/protected-set/receipt support exists;
- development-to-durable promotion automation before a concrete consumer requires it;
- production queue execution and storage-resident lifecycle mutation;
- host-level timer enablement without operator review.

## Recently Accepted

- Accepted the V0.1 storage lifecycle system design in `docs/91_storage_lifecycle_policy.md` through `docs/95_lifecycle_receipts.md`, including lifecycle states, manager-unified lifecycle requests/task visibility, artifact index, reproducibility/retention/read-mode classes, protected-set builder, quarantine-before-delete, compression/archive/restore flows, lifecycle receipts, and tombstones. Implementation remains future controlled slices and is dry-run-first.
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
