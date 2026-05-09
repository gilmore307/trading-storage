# src

Importable storage helpers live here.

## Boundary

- `trading_storage.artifact_store` owns canonical JSON artifact writing for storage-owned payloads and returns `artifact_ref_v1` metadata.
- It does not mutate manager SQL, dispatch component work, call providers, or interpret model/execution decisions.
- Scripts may import this package; this package must not import from `scripts/`.
