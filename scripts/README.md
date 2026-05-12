# scripts

Executable storage maintenance and artifact helpers live here. Scripts may import `src/`; `src/` must not import scripts.

## Dashboard helpers

- `dashboard/materialize_read_model.py` validates a dashboard read-model common envelope and writes storage-owned snapshot/latest/schema/index files under `storage/dashboard/`.
- `dashboard/refresh_historical_task_progress_read_model.py` runs the manager-owned `historical_task_progress_summary_v1` producer and materializes the validated payload into the accepted storage layout.

Examples:

```bash
PYTHONPATH=src python3 scripts/dashboard/materialize_read_model.py summary.json \
  --contract-type current_system_status_summary_v1

PYTHONPATH=src python3 scripts/dashboard/refresh_historical_task_progress_read_model.py \
  --trading-manager-root /root/projects/trading-manager \
  --storage-root storage
```

## Lifecycle helpers

- `lifecycle/maintain_local_storage.py` plans or applies conservative local retention rules for ignored runtime files.

Dry-run:

```bash
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root .
```

Apply after review:

```bash
PYTHONPATH=src python3 scripts/lifecycle/maintain_local_storage.py --root . --apply
```

## Artifact helpers

- `artifacts/store_completion_receipt_payload.py` stores a component completion receipt JSON as a storage-owned `component_completion_receipt_payload_v1` artifact and prints `artifact_ref_v1` metadata.

Example:

```bash
PYTHONPATH=src python3 scripts/artifacts/store_completion_receipt_payload.py receipt.json \
  --request-id mgrreq_backfill_alpaca_bars_2016_01 \
  --run-id run_backfill_alpaca_bars_2016_01_dryrun \
  --producer-repo trading-data \
  --workflow-id 01_feed_alpaca_bars
```
