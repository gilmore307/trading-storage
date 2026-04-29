# Fetch Spec: <source-name>

## Purpose

Define exactly how `pipeline.py::fetch` retrieves historical source data for this source.

## Source And Authentication

- Provider/source term:
- Documentation URL:
- Credential config id or no-key rule:
- Required source-secret JSON fields, if any:
- Official source URL validation rule, if web/issuer sourced:

## API / Source Requirements

| Requirement | Value |
|---|---|
| Endpoint or URL pattern | |
| HTTP method / local terminal method | |
| Required parameters | |
| Optional parameters | |
| Pagination / cursor behavior | |
| Rate limits / quotas | |
| Retryable errors | |
| Non-retryable errors | |
| Timestamp timezone | |
| Historical range limits | |

## Task Key Inputs Used

List exact task key fields consumed by fetch.

## Raw Output

Development raw outputs must be written under:

```text
storage/<task-id>/runs/<run-id>/raw/
```

Record:

- request URL or source locator;
- request parameters actually used;
- retrieval timestamp;
- response status / source file metadata;
- raw payload path(s).

## Failure Behavior

Fetch failures should still allow `pipeline.py::write_receipt` to emit a failed completion receipt.

## Default Test Policy

Default tests must not call live provider APIs or live websites. Use mocked clients, local sample files, or sanitized fixtures.
