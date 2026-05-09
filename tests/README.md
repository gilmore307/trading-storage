# tests

First-party tests for storage implementation slices.

## Current coverage

- `test_artifact_store.py` verifies canonical JSON bytes, immutable artifact writes, `artifact_ref_v1` metadata, and storage-owned completion receipt payload wrapping.
- `test_lifecycle.py` verifies dry-run planning, temporary-file deletion, archive-before-remove behavior, durable artifact retention, and JSON output shape.

## Default command

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
