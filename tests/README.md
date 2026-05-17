# tests

First-party tests for storage implementation slices.

## Current coverage

- `test_artifact_store.py` verifies canonical JSON bytes, immutable artifact writes, `artifact_ref` metadata, and storage-owned completion receipt payload wrapping.
- `test_artifact_index.py` verifies conservative filesystem artifact indexing, explicit dashboard read-model indexing, and JSONL/summary writes.
- `test_file_lifecycle_acceptance.py` verifies the one-pass safe file-lifecycle acceptance, compressed-copy-only apply behavior, original preservation, output evidence writes, dashboard deletion hold, and dashboard latest protected-set reason handling.
- `test_lifecycle.py` verifies dry-run planning, temporary-file deletion, archive-before-remove behavior, durable artifact retention, and JSON output shape.
- `test_lifecycle_execution_scaffold.py` verifies non-mutating compression/archive/restore manifest and receipt drafts, protected skip behavior, no delete receipts for quarantine candidates, and JSON output round trips.
- `test_lifecycle_planner.py` verifies durable-artifact dry-run lifecycle planning, protected retention, compression/quarantine/archive candidates, evidence retention, policy loading, and JSON output round trips.
- `test_protected_set.py` verifies conservative protected-set blocking, manual pins, reason-code reference matching, clear-candidate reporting, and JSON output round trips.
- `test_quarantine_recheck.py` verifies report-only quarantine/recheck evidence, initial/final protected-set blocking, pending recheck status, clear recheck evidence without deletion authorization, and JSON output round trips.
- `test_single_file_compression.py` verifies dry-run and applied single-file zstd compressed-copy behavior, original preservation, restore checksum smoke, protected/quarantine skips, existing-output refusal, and JSON output round trips.
- `test_dashboard_read_models.py` verifies common dashboard read-model envelope validation, unsafe payload rejection, and snapshot/latest/schema/index materialization.
- `test_dashboard_refresh.py` verifies storage-owned refresh orchestration from semantic producer output into `storage/dashboard`, including no provider/model/broker/account side-effect flags.
- `test_dashboard_snapshot_lifecycle.py` verifies dashboard snapshot metadata dry-run/apply pruning, latest preservation, Layer 1/2/SQL non-mutation summary flags, and plan/summary output writes.

## Default command

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
