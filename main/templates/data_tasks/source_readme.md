# <source-name>

## Purpose

Describe the historical data this source acquires/prepares and why this manager-facing source boundary exists.

## Source Inputs

- Provider/feed term:
- Documentation URL:
- Credential config id or no-key rule:
- Official feed URL rule, if web/issuer sourced:

## Source Boundary

This source includes:

- `<data-type-1>`
- `<data-type-2>`

This source excludes:

- realtime data;
- execution-time feeds;
- derived/model decisions;
- durable SQL writes during development unless an accepted storage contract exists.

## Task Key Inputs

Required task key fields:

- `task_id`
- `source`
- `params`
- `output_root`

Optional task key fields:

- `credential_config_id` when the source needs a registered credential alias

Put API-specific inputs such as symbols, underlyings, ETF ids, macro release keys, calendar scope, time ranges, snapshot timestamps, granularity, feed URLs, and provider parameters inside `params`. Do not put provider documentation URLs in the task key; those belong in scripts/provider docs or this README. Do not put `run_id` in the task key; it changes per invocation and belongs in receipt `runs[]`.

## Pipeline Module

Default implementation should start as one `pipeline.py` file with one public `run(task_key, run_id=...)` entry point and four internal step functions. Split into separate modules only when complexity makes a single file hard to maintain.

| Step function | Responsibility |
|---|---|
| `fetch(...)` | Retrieve feed data and write raw development files. |
| `clean(...)` | Normalize provider/feed data into source output shapes. |
| `save(...)` | Save cleaned development files under `storage/`; durable SQL waits for contracts. |
| `write_receipt(...)` | Emit success/failure completion receipt. |

## Outputs

Development outputs should be grouped by task/run:

```text
storage/<task-id>/
  task_key.json
  completion_receipt.json
  runs/
    <run-id>/
      raw/
      cleaned/
      saved/
```

## API Requirements

Document provider-specific requirements here:

- endpoint(s) or web source(s);
- required request parameters;
- pagination;
- rate limits;
- timestamp/timezone semantics;
- revision/vintage/as-of behavior;
- provider caveats;
- response fields used;
- response fields ignored.

## Tests And Fixtures

Default tests must use fixtures or mocks. Live calls require explicit opt-in guardrails.
