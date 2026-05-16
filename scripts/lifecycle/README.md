# Lifecycle Scripts

Executable local storage lifecycle helpers live here.

## Current entrypoints

- `build_artifact_index.py` scans storage-owned filesystem artifacts/read models and emits conservative JSONL inventory metadata according to `docs/92_artifact_index.md`.
- `build_protected_set.py` builds conservative protected-set safety evidence from artifact-index records and optional reason-code references/manual pins according to `docs/93_protected_set.md`.
- `maintain_local_storage.py` plans or applies conservative cleanup for ignored runtime files according to `docs/91_storage_lifecycle_policy.md`.
- `plan_storage_lifecycle.py` emits non-mutating durable-artifact lifecycle plans from artifact-index/protected-set/policy evidence according to `docs/91_storage_lifecycle_policy.md`.
- `build_quarantine_recheck_evidence.py` emits report-only quarantine/recheck gate evidence from lifecycle plans and optional final protected-set evidence according to `docs/93_protected_set.md`.

Scripts in this directory may import `src/trading_storage`; reusable lifecycle logic belongs in `src/`, not here.
