# scripts

Executable storage maintenance and artifact helpers live here.

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
