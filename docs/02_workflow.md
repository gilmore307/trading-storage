# Workflow

## Purpose

This file defines the intended component workflow for `trading-storage`.

## Primary Flow

```text
artifact contract -> storage layout -> write/read policy -> retention/archive policy -> restore/rehydrate evidence
```

## Operating Principles

- Producers write artifacts according to storage contracts rather than inventing local paths.
- Consumers dereference artifacts through documented references and layout rules.
- Backup and restore expectations must be explicit before important data depends on the storage layer.
- Shared fields, statuses, type values, helpers, and reusable templates must come from `trading-main`.
- Runtime outputs must be written outside Git-tracked source paths.
- Cross-repository handoffs should use accepted request, artifact, manifest, and ready-signal contracts.


## Data Task Storage Role

For historical data acquisition, `trading-storage` should eventually provide the SQL table/partition contract named by `trading-data` task key files and the durable location/schema for data task completion receipts.

`trading-storage` owns persistence shape, retention, backup/restore, and reference rules. It does not decide provider semantics, normalize rows, or manage task lifecycle.

## Collaboration Boundary

`trading-storage` collaborates with other trading repositories through explicit contracts, not direct mutation of their local state.

Upstream inputs and downstream outputs should be described by artifact references, manifests, ready signals, requests, or accepted storage contracts.

## Open Gaps

- Exact first implementation slice.
- Exact request/task-key/completion-receipt shape consumed or produced by this repository.
- Exact artifact, manifest, and ready-signal schema interactions.
- Exact shared storage paths, SQL table/partition contracts, and completion receipt references.
- Exact test harness and fixture policy.
- Exact package/source layout once implementation begins.
