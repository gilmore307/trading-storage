# tests

First-party tests for storage implementation slices.

## Current coverage

- `test_artifact_store.py` verifies canonical JSON bytes, immutable artifact writes, `artifact_ref_v1` metadata, and storage-owned completion receipt payload wrapping.
- `test_lifecycle.py` verifies dry-run planning, temporary-file deletion, archive-before-remove behavior, durable artifact retention, and JSON output shape.
- `test_dashboard_read_models.py` verifies common dashboard read-model envelope validation, unsafe payload rejection, and snapshot/latest/schema/index materialization.
- `test_dashboard_refresh.py` verifies storage-owned refresh orchestration from semantic producer output into `storage/dashboard`, including no provider/model/broker/account side-effect flags.

## Default command

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
