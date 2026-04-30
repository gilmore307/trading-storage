# Scope

## Purpose

`trading-storage` is the shared persistence contract repository for the trading system.

It defines durable artifact layout, references, retention, archive, restore, backup, and rehydrate expectations used by source, derived, model, execution, dashboard, and manager workflows. It also owns checked-in reusable non-code assets under `main/`.

This repository exists to keep that responsibility explicit, testable, and separate from neighboring trading repositories.

## In Scope

- shared artifact storage layout contracts.
- checked-in reusable templates and shared static files under `main/`.
- artifact reference and path policy in coordination with trading-main contracts.
- retention, archive, rehydrate, backup, and restore expectations.
- storage validation and compatibility checks once implementation exists.
- storage-local tests for path/reference/retention helpers once code exists.

## Out of Scope

- market data fetching.
- derived or model logic.
- execution/order placement.
- dashboard visualization.
- global contract/type registration outside trading-main.
- committed generated artifacts or production data.
- Defining global artifact, manifest, ready-signal, request, field, status, or type contracts outside `trading-main`.
- Storing generated data, artifacts, logs, notebooks, credentials, or secrets in Git.

## Owner Intent

`trading-storage` should become a disciplined component repository with clear contracts, evidence-backed acceptance, and no hidden ownership drift.

The repository should prefer explicit interfaces, fixture-backed tests, and narrow responsibility boundaries over quick scripts that blur component roles.

## Boundary Rules

- Component-local implementation belongs here only when it matches this repository's role.
- Global contracts, registry entries, shared helpers, and template operating rules belong in `trading-main`; checked-in reusable template files live under `trading-storage/main/templates/`.
- Durable storage layout and retention belong in `trading-storage` unless this repository is defining that storage contract.
- Scheduling, retries, lifecycle routing, and promotion decisions belong in the `trading-main` control plane unless explicitly delegated by contract.
- Generated artifacts and runtime outputs are not source files.
- Secrets and credentials must stay outside the repository.
- Shared helpers, templates, fields, statuses, and type values discovered here must be recorded through `trading-main` before cross-repository use.

## Out-of-Scope Signals

A request should be rejected or re-scoped if it asks `trading-storage` to:

- take over another component repository responsibility.
- commit generated runtime outputs or secrets.
- define global contracts without routing them through trading-main.
- invent shared fields/statuses/types without registry review.
- bypass accepted storage or manager lifecycle boundaries.
