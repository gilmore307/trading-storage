# src

Importable storage helpers live here.

## Boundary

- `trading_storage.artifact_store` owns canonical JSON artifact writing for storage-owned payloads and returns `artifact_ref` metadata.
- `trading_storage.lifecycle` owns conservative local retention planning/application for ignored runtime files.
- Helpers do not mutate manager SQL, dispatch component work, call providers, activate models, execute trades, or interpret model/execution decisions.
- Scripts may import this package; this package must not import from `scripts/`.
