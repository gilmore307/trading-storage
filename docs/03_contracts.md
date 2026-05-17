# Contracts

## Status

The current `trading-storage` storage-contract-and-lifecycle-helper phase is closed.

This acceptance covers the storage-owned surfaces needed by the current data/model/manager phase:

- repository boundary and docs spine;
- reusable checked-in non-code assets under `main/`;
- V1 handoff templates for `manager_request`, `run_manifest`, `artifact_ref`, and `ready_signal`, with semantic ownership separated from physical persistence/layout ownership;
- storage-owned completion receipt payload helper;
- local ignored `storage/` development artifact boundary;
- local retention/archive/cleanup helper and scheduling templates;
- package/source/test layout for future storage helpers.

## Accepted Storage-Owned Shape

`trading-storage` owns physical persistence contracts, storage URI policy, retention/archive/restore behavior, and payload durability boundaries. It does not own component semantics or manager orchestration. `trading-manager` owns semantic lifecycle/routing/readiness behavior for `manager_request`, `run_manifest`, and `ready_signal`; `artifact_ref` has the strongest storage-owned physical contract surface while remaining registered through the manager registry.

The accepted current shape is:

```text
component completion receipt JSON
  -> storage-owned payload write
  -> artifact_ref metadata
  -> manager records concise run/artifact/ready facts
```

The accepted V1 templates live under:

```text
main/templates/contracts/
```

The accepted implementation helpers are:

```text
src/trading_storage/artifact_store.py
scripts/artifacts/store_completion_receipt_payload.py
src/trading_storage/lifecycle.py
scripts/lifecycle/maintain_local_storage.py
```

## Boundaries Preserved

This acceptance does not enable or claim:

- production object-store infrastructure;
- production SQL partitioning for every output family;
- production queue execution;
- host-level timer installation or manager lifecycle mutation;
- provider calls;
- model promotion approval;
- broker/order/fill/account lifecycle;
- dashboard rendering.

Those are later component production phases and must be accepted through the manager/storage handoff route before implementation.

## Not Current Historical-Training Scope

There are no active storage work items for the current no-broker historical-training preparation boundary. Future storage work should begin only when a concrete manager/component consumer requires it:

- physical SQL DDL for durable request/manifest/artifact/ready persistence beyond current manager MVP rows;
- object-store backend policy and production backup/restore infrastructure beyond the local filesystem helper;
- SQL retention policy by source/feature/model output family;
- development-to-durable promotion automation for source/feature/model outputs;
- partitioning/index policy for high-volume artifacts;
- lifecycle mutation rules for storage-resident artifacts after manager consumers require them.

These are not blockers for current historical training.

## Acceptance Evidence

The acceptance is acceptable only while these gates pass:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src scripts
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root .
git diff --check
```

No command in this acceptance performs provider calls, manager dispatch, model activation, broker execution, or production storage mutation.
