# Contract Templates

This directory stores the accepted V1 template contracts for cross-repository trading handoffs.

Templates live here because `trading-storage` owns durable artifact/storage semantics. `trading-manager` registers stable type names and orchestrates when these contracts are emitted or consumed.

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

See `trading-manager/docs/13_templates.md` for template promotion rules.
