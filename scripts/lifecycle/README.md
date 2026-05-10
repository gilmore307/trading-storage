# Lifecycle Scripts

Executable local storage lifecycle helpers live here.

## Current entrypoints

- `maintain_local_storage.py` plans or applies conservative cleanup for ignored runtime files according to `docs/04_storage_lifecycle.md`.

Scripts in this directory may import `src/trading_storage`; reusable lifecycle logic belongs in `src/`, not here.
