# Artifact Contract

## Purpose

`artifact_ref` is the durable cross-repository reference for an immutable output artifact. It lets `trading-manager`, `trading-data`, `trading-model`, `trading-storage`, and downstream consumers refer to a produced file/table/object without depending on local development paths.

Artifacts are not readiness by themselves. A consumer may use an artifact only when a compatible manifest and ready signal authorize it.

## Contract Type

- **Type name:** `artifact_ref`
- **Owning repository:** `trading-storage`
- **Registered through:** `trading-manager/scripts/registry/`
- **Status:** Accepted template contract; production instances still require manager/storage implementation.

## Required Fields

| Field | Meaning |
| --- | --- |
| `contract_type` | Must be `artifact_ref`. |
| `schema_version` | Integer schema version, currently `1`. |
| `artifact_id` | Stable immutable artifact id. A new content version gets a new id. |
| `artifact_type` | Registered artifact type or reviewed local type while unpromoted. |
| `producer_repo` | Repository that produced the artifact. |
| `producer_workflow` | Stable workflow/script/source identifier. |
| `produced_at` | UTC timestamp when the artifact was finalized. |
| `storage_backend` | Storage backend class, e.g. `postgres`, `object_store`, `filesystem`, or `registry_snapshot`. |
| `storage_uri` | Durable locator. Must not be a transient local development path for production artifacts. |
| `content_format` | File/table payload format such as `csv`, `json`, `jsonl`, `parquet`, `postgres_table`, or `sqlite`. |
| `schema_ref` | Reference to the schema/contract used to interpret the payload. |
| `content_hash_sha256` | Hash over canonical content bytes or over an accepted table/export digest. |
| `mutability` | Must be `immutable` for production handoff. |
| `visibility_time` | Earliest point-in-time timestamp at which the artifact may be used. |
| `retention_policy` | Retention/archive rule key. |
| `manifest_id` | Producing run manifest id. |

## Optional Fields

- `partition`: object with reviewed partition keys such as trading date, symbol, layer, provider, or run date.
- `byte_count`, `row_count`: integrity metadata where meaningful.
- `source_time_range`: `{ "start": "...", "end": "...", "timezone": "..." }` for time-windowed data.
- `lineage_refs`: upstream artifact ids.
- `quality_summary`: compact quality/gate summary; detailed checks belong in the manifest.

## JSON Shape

```json
{
  "contract_type": "artifact_ref",
  "schema_version": 1,
  "artifact_id": "art_...",
  "artifact_type": "model_eval_labels",
  "producer_repo": "trading-model",
  "producer_workflow": "model_03_target_state_vector_evaluate",
  "produced_at": "2026-05-08T08:00:00Z",
  "storage_backend": "postgres",
  "storage_uri": "postgres://trading_model.model_eval_label?eval_run_id=mdevrun_...",
  "content_format": "postgres_table",
  "schema_ref": "trading-model/src/model_governance/evaluation/schema.py",
  "content_hash_sha256": "...",
  "mutability": "immutable",
  "visibility_time": "2026-05-08T08:00:00Z",
  "retention_policy": "promotion_evidence_retained",
  "manifest_id": "mf_..."
}
```

## Rules

- Do not overwrite production artifacts. Produce a new artifact id for any content change.
- Do not use ignored `storage/` paths as production artifact locators.
- Do not embed secrets, raw provider credentials, broker account secrets, or private token values.
- A path or URI is only consumable when the manifest validation passed and a ready signal marks it ready.
- Local fixture/development artifacts may use this shape for rehearsal, but must set non-production artifact types/status in the producing manifest.
