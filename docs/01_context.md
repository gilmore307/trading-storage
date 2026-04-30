# Context

## Why This Repository Exists

The trading platform is split across multiple repositories so each major responsibility has a clear owner. `trading-storage` exists because it defines durable artifact layout, references, retention, archive, restore, backup, and rehydrate expectations used by data, model, execution, dashboard, and manager workflows. It also owns checked-in reusable non-code assets under `main/`.

## Related Systems

| System | Relationship |
|---|---|
| `trading-main` | Owns global architecture, registry, template operating rules, shared helpers, and cross-repository contracts. |
| `trading-manager` | Owns orchestration, lifecycle, scheduling, retries, requests, and promotion routing. |
| `trading-data` | Produces feed evidence, source tables, deterministic feature tables, manifests, and ready signals. |
| `trading-storage` | Owns durable storage layout, retention, archive, backup, restore, and artifact placement rules. |
| `trading-model` | Produces offline model/state research outputs and verdicts. |
| `trading-execution` | Consumes promoted decisions for paper/live execution. |
| `trading-dashboard` | Presents already-produced outputs and evidence. |

## Expected External Interfaces

Potential external interfaces include:

- local/shared filesystem storage.
- backup/archive targets once chosen.
- trading-main artifact and manifest contracts.
- checked-in shared assets under `main/`, including reusable templates and shared static CSVs.

Specific providers, credentials, package choices, deployment targets, and runtime settings are not settled unless recorded in this repository's decisions or inherited from `trading-main` contracts.

## Environment

Development is server-hosted under `/root/projects/trading-storage`.

The shared Python environment is anchored by `trading-main` at:

```text
/root/projects/trading-main/.venv
```

`trading-storage` should not create an independent virtual environment unless a documented exception is accepted.

## Dependencies

Current system-level dependencies:

- `trading-main/docs/07_helpers.md` for shared helper policy;
- `trading-main/docs/08_registry.md` for registry operating rules;
- `trading-main/docs/09_templates.md` for reusable template operating rules;
- `trading-storage/main/templates/` for reusable drafting surfaces;
- `trading-main/requirements.txt` for reviewed shared Python dependencies;
- related component repositories through accepted contracts, not internal implementation details.

## Global Registration Discipline

If this repository introduces a name that other repositories may consume, route it back to `trading-main` before treating it as stable.

This includes shared fields, artifact types, manifest types, ready-signal types, request types, status values, global helper methods, reusable templates, config keys, and provider-independent terminology.

## Important Constraints

- Do not store generated artifacts, logs, notebooks, credentials, or secrets in Git.
- Keep component-local implementation inside this repository's boundary.
- Use manifests, ready signals, artifact references, and requests for cross-repository handoffs once contracts are accepted.
- Do not depend on another component's internal implementation details.
