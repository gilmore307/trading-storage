# Save Spec: <source-name>

## Purpose

Define how `pipeline.py::save` writes cleaned outputs during development and how it will later map to durable storage contracts.

## Development Save Rule

During development, save only to local files under:

```text
storage/<task-id>/runs/<run-id>/saved/
```

Do not write to SQL by default.

## Development Output Layout

| Output | Source cleaned file(s) | Saved file path | Format | Partition keys |
|---|---|---|---|---|
| `<output-name>` | | | | |

## Idempotency And Overwrite Policy

- Stable task id field:
- Run id field:
- Default overwrite policy:
- Existing run directory behavior:
- Partial save rollback/cleanup behavior:

## Future Durable Mapping

Document intended future durable target, without implementing it yet:

| Output | Future SQL table/artifact target | Required contract | Open questions |
|---|---|---|---|
| `<output-name>` | | | |

## Save Evidence

`pipeline.py::save` should produce evidence for receipt generation:

- saved file paths;
- row counts;
- checksums if practical;
- partition values;
- skipped/failed outputs;
- warnings.

## Default Test Policy

Default tests may write to temporary directories only. They must not write to SQL or persistent databases.
