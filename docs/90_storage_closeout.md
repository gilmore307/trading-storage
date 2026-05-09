# Storage Closeout

## Status

The current `trading-storage` storage-contract-and-first-helper phase is closed.

This closeout covers the storage-owned surfaces needed by the current data/model/manager phase:

- repository boundary and docs spine;
- reusable checked-in non-code assets under `main/`;
- V1 handoff templates for `manager_request_v1`, `run_manifest_v1`, `artifact_ref_v1`, and `ready_signal_v1`;
- storage-owned completion receipt payload helper;
- local ignored `storage/` development artifact boundary;
- package/source/test layout for future storage helpers.

## Accepted Storage-Owned Shape

`trading-storage` owns persistence contracts and payload durability boundaries, not component semantics and not manager orchestration.

The accepted current shape is:

```text
component completion receipt JSON
  -> storage-owned payload write
  -> artifact_ref_v1 metadata
  -> manager records concise run/artifact/ready facts
```

The accepted V1 templates live under:

```text
main/templates/contracts/
```

The first implementation helper is:

```text
src/trading_storage/artifact_store.py
scripts/artifacts/store_completion_receipt_payload.py
```

## Boundaries Preserved

This closeout does not enable or claim:

- production object-store infrastructure;
- production SQL partitioning for every output family;
- production queue execution;
- manager lifecycle mutation;
- provider calls;
- model promotion approval;
- broker/order/fill/account lifecycle;
- dashboard rendering.

Those are later component production phases and must be accepted through the manager/storage handoff route before implementation.

## Deferred Beyond This Closeout

Future storage work should begin only when a concrete manager/component consumer requires it:

- physical SQL DDL for durable request/manifest/artifact/ready persistence beyond current manager MVP rows;
- object-store backend policy, retention, backup, restore, archive, and rehydrate mechanics beyond the local filesystem helper;
- development-to-durable promotion automation for source/feature/model outputs;
- partitioning/index policy for high-volume artifacts;
- lifecycle mutation rules for storage-resident artifacts after manager consumers require them.

These are not blockers for closing the current storage phase.

## Acceptance Evidence

The closeout is acceptable only while these gates pass:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src scripts
git diff --check
```

No command in this closeout performs provider calls, manager dispatch, model activation, broker execution, or production storage mutation.
