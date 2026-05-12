# Fixture Policy: <source-name>

## Purpose

Define safe fixture and provider-call rules for this data-source source.

## Default Tests

Default tests must not require:

- live provider credentials;
- network access;
- paid quota;
- current market state;
- mutable provider responses.

## Fixture Sources

Allowed fixture sources:

- hand-authored minimal examples;
- sanitized provider responses;
- mocked client outputs;
- small public examples when license permits.

Disallowed fixture content:

- API keys, tokens, passwords, account ids, private endpoints, or raw credentials;
- large provider dumps;
- personal/private account data;
- files whose license or redistribution status is unclear.

## Sanitization Checklist

Before committing fixtures, confirm:

- no secret values;
- no account identifiers;
- no unnecessary raw payload volume;
- source URL and retrieval date are documented when relevant;
- timestamp and timezone examples are preserved;
- edge cases are intentionally represented.

## Provider Call Guardrail

Provider calls require an explicit opt-in mechanism, such as manager-issued autonomous historical acquisition controls, an environment variable, or a separate manual command. Document:

- required secret alias;
- expected quota impact;
- expected runtime;
- safe request size;
- cleanup behavior;
- evidence produced.

## Fixture Inventory

| Fixture | Purpose | Source/sanitization note | Tests using it |
|---|---|---|---|
| `<fixture-file>` | | | |
