# Clean Spec: <source-name>

## Purpose

Define how `pipeline.py::clean` converts raw provider/feed data into normalized development outputs.

## Inputs

- Raw input directory: `storage/<task-id>/runs/<run-id>/raw/`
- Required raw file names or patterns:
- Required task key fields:

## Normalized Output Shapes

For each output data type, document:

| Output | Required columns/fields | Types | Null policy | Notes |
|---|---|---|---|---|
| `<output-name>` | | | | |

## Timestamp And Calendar Rules

- Input timestamp timezone:
- Output timestamp timezone:
- Session/calendar alignment rule:
- Snapshot/as-of/release-time rule:

## Provider-Specific Caveats

Document provider nulls, placeholders, revisions, duplicate behavior, delayed fields, adjusted/unadjusted behavior, or issuer-specific quirks.

## Validation Preparation

Document checks that clean must prepare evidence for:

- schema presence;
- timestamp parseability;
- duplicate keys;
- row counts;
- expected coverage;
- source URL/as-of/release metadata.

## Cleaned Output

Development cleaned outputs must be written under:

```text
storage/<task-id>/runs/<run-id>/cleaned/
```

## Default Test Policy

Default tests should run against deterministic raw fixtures and assert cleaned shapes without live calls.
