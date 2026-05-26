# Scope

## Purpose

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, references, retention, archive, restore, backup, and rehydrate expectations used by source, derived, model, execution, dashboard, and manager workflows. It also owns checked-in reusable non-code assets under `main/`.

This repository exists to keep that responsibility explicit, testable, and separate from neighboring trading repositories.

## In Scope

- shared artifact storage layout contracts.
- durable non-SQL saved data contracts for files, JSON/JSONL/CSV/parquet payloads, summaries, manifests, receipts, model bodies, archives, and object-like artifacts.
- checked-in reusable templates and shared static files under `main/`.
- artifact reference and path policy in coordination with trading-manager contracts.
- retention, archive, rehydrate, backup, and restore expectations.
- conservative local lifecycle maintenance for ignored runtime files.
- storage-owned disposable cache/tmp/local-staging roots and scheduled cleanup policy for trading runtime outputs.
- storage validation and compatibility checks.
- storage-local tests for path/reference/retention helpers.

## Out of Scope

- market data fetching.
- derived or model logic.
- execution/order placement.
- dashboard visualization.
- global contract/type registration outside trading-manager.
- committed generated artifacts or production data, except the accepted Trading Economics source-data Git exception.
- Defining global artifact, manifest, ready-signal, request, field, status, or type contracts outside `trading-manager`.
- Storing generated data, artifacts, logs, notebooks, credentials, or secrets in Git, except the accepted Trading Economics source-data Git exception.

## Durable Non-SQL Data Rule

Any durable, system-owned data that is not stored in SQL should be stored through `trading-storage` contracts and storage-owned locations. This includes durable files, JSON/JSONL/CSV/parquet payloads, manifests, receipts, model bodies, dashboard summaries, archives, tombstones, and restore manifests.

This rule does not move semantic ownership: producing repositories still own the meaning and validation of their outputs. Storage owns physical placement, references, retention, backup, restore, archive, and lifecycle.

Allowed exceptions:

- source code, tests, docs, checked-in templates, reviewed shared static files, and registry exports that belong in Git;
- secrets under approved secret storage outside repositories;
- unavoidable tool-created source-adjacent caches such as `__pycache__/` or `.pytest_cache/`, which are never system data and remain disposable;
- database-resident SQL rows/tables/partitions, whose durable SQL contracts remain SQL/storage contract work rather than file placement.
- the accepted Trading Economics source-data Git exception at `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/`, excluding `_manifests/`; this exception exists because those provider-window source payloads are the canonical macro source and must be Git-recoverable.

Trading runtime disposable cache, temporary output, and local staging should also use storage-owned ignored roots and storage-owned cleanup policy. Component repositories should not create ad hoc durable-looking `tmp/`, `cache/`, `runs/`, `outputs/`, or `staging/` homes as final or semi-final runtime locations.

## Owner Intent

`trading-storage` should become a disciplined component repository with clear contracts, evidence-backed acceptance, and no hidden ownership drift.

The repository should prefer explicit interfaces, fixture-backed tests, and narrow responsibility boundaries over quick scripts that blur component roles.

## Boundary Rules

- Component-local implementation belongs here only when it matches this repository's role.
- Global contracts, registry entries, shared helpers, and template operating rules belong in `trading-manager`; checked-in reusable template files live under `trading-storage/main/templates/`.
- Durable storage layout and retention belong in `trading-storage` unless this repository is defining that storage contract.
- Scheduling, retries, cross-component lifecycle routing, and promotion decisions belong in the `trading-manager` control plane unless explicitly delegated by contract; storage may provide local maintenance helpers and installable scheduling templates.
- Generated artifacts and runtime outputs are not source files.
- The only production-data Git exception is canonical Trading Economics source data under `storage/01_source_data/monthly_backfill/trading_economics_calendar_web/`, excluding `_manifests/`; SQL rows, runtime receipts, control-plane artifacts, dashboard caches, and lifecycle outputs remain derived or operational state.
- Durable or system-owned non-SQL saved data belongs under storage-owned contracts/locations, not scattered as ad hoc saved files in component repositories.
- Trading runtime disposable cache/tmp/local staging also belongs under storage-owned ignored roots so scheduled cleanup can be uniform.
- Secrets and credentials must stay outside the repository.
- Shared helpers, templates, fields, statuses, and type values discovered here must be recorded through `trading-manager` before cross-repository use.

## Out-of-Scope Signals

A request should be rejected or re-scoped if it asks `trading-storage` to:

- take over another component repository responsibility.
- commit generated runtime outputs or secrets.
- define global contracts without routing them through trading-manager.
- invent shared fields/statuses/types without registry review.
- bypass accepted storage or manager lifecycle boundaries.
