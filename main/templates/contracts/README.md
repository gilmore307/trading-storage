# Contract Templates

This directory stores the accepted V1 template contracts for cross-repository trading handoffs.

Templates live here because `trading-storage` owns durable physical persistence/layout support for cross-repository handoffs. `trading-manager` owns the semantic lifecycle for request, run, artifact, and ready-signal control-plane records; it also registers stable type names and orchestrates when these contracts are emitted or consumed.

Ownership convention:

- `trading-manager`: semantic owner for `manager_request`, `run_manifest`, and `ready_signal` lifecycle/routing/readiness behavior.
- `trading-storage`: physical persistence/layout owner for durable contract payloads, storage URI policy, retention, archive, and restore behavior.
- `artifact_ref`: storage has the strongest physical-contract ownership, while stable names and control-plane rows remain registered through the manager registry.

Current contracts:

- `request.md` — `manager_request`, the manager-issued work-intent contract.
- `manifest.md` — `run_manifest`, the durable run-evidence contract.
- `artifact.md` — `artifact_ref`, the immutable output-artifact reference contract.
- `ready_signal.md` — `ready_signal`, the downstream consumability marker.

Relationship:

```text
manager_request
  -> run_manifest
      -> artifact_ref
      -> ready_signal
```

Acceptance rules:

- Production instances must not use ignored local `storage/` paths as durable handoff locators.
- Secrets are referenced by registry/config aliases only.
- Ready signals authorize consumption only when referenced manifests and validation checks support that status.
- Fixture/local evidence may rehearse these shapes, but cannot become production-ready without reviewed manager/storage implementation.

When a type name becomes stable, register it in `trading-manager/scripts/registry/` through SQL migrations and regenerate `trading-manager/scripts/registry/current.csv`.

See `trading-manager/docs/11_templates.md` for template promotion rules.
