# Artifact Scripts

Executable artifact-storage helpers live here.

## Current entrypoints

- `store_completion_receipt_payload.py` stores a component completion receipt JSON payload under the ignored storage artifact root and prints `artifact_ref` metadata.

Scripts in this directory may import `src/trading_storage`; reusable implementation logic belongs in `src/`, not here.
