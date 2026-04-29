# Data Task Templates

Reusable draft templates for manager-driven `trading-source` historical acquisition tasks.

These templates are cross-repository planning surfaces:

- `trading-manager` uses the task-key shape to request work;
- `trading-source` uses source templates to implement fetch, clean, save, and receipt steps;
- `trading-storage` uses receipt/output references later when durable contracts are accepted.

Legacy development-stage file outputs should target ignored local `trading-source/storage/` paths until a durable SQL/artifact contract exists.

## Templates

- `task_key.json` — draft manager-issued historical data task key.
- `source_readme.md` — per-source documentation template.
- `pipeline.py` — default single-file source implementation template with four step functions.
- `fetch_spec.md` — provider/API fetch requirement template.
- `clean_spec.md` — normalization and validation preparation template.
- `save_spec.md` — development-save and future durable-save template.
- `completion_receipt.json` — draft task completion receipt shape.
- `fixture_policy.md` — per-source fixture and live-call guardrail template.

## Minimalism Rule

Task key and completion receipt templates should contain only fields the runner, source, manager, or development evidence path will actually use. Do not add lookup/reference metadata such as provider documentation URLs when those values already live in the registry or source README.

A task key is stable across many invocations, including periodic or scheduled tasks. Per-run data belongs in the task-level completion receipt under `runs[]`.

## Boundary

These are templates, not accepted concrete schemas. Stable schema fields, status values, request types, artifact types, and storage contracts still require scripts/docs review before implementation treats them as durable contracts.

No template may contain provider secret values, raw credentials, generated data, or account-specific private configuration.

## Implementation Shape

By default, a source should start as one `pipeline.py` file exposing one `run(task_key, run_id=...)` entry point and internal `fetch`, `clean`, `save`, and `write_receipt` functions. Split those functions into separate modules only when the source becomes large enough to justify the extra structure.
