# Manifest Contract

## Purpose

`run_manifest` is the durable evidence record for one completed or failed cross-repository run. It records the request, code/config, inputs, outputs, validation checks, and final usability state.

A manifest explains what happened. It does not by itself authorize downstream consumption; that is the job of `ready_signal`.

## Contract Type

- **Type name:** `run_manifest`
- **Owning repository:** `trading-storage`
- **Registered through:** `trading-manager/scripts/registry/`
- **Status:** Accepted template contract; production persistence still requires manager/storage implementation.

## Required Fields

| Field | Meaning |
| --- | --- |
| `contract_type` | Must be `run_manifest`. |
| `schema_version` | Integer schema version, currently `1`. |
| `manifest_id` | Stable manifest id. |
| `request_id` | Manager request id, or `manual:<id>` for reviewed manual runs. |
| `run_id` | Producer-local run id. |
| `producer_repo` | Repository that executed the run. |
| `workflow_id` | Stable workflow/script/source/model id. |
| `workflow_kind` | `data_feed`, `data_source`, `data_feature`, `model_generate`, `model_evaluate`, `model_review`, `registry_migration`, or another registered/reviewed kind. |
| `started_at` | UTC run start timestamp. |
| `finished_at` | UTC run end timestamp. |
| `run_status` | `succeeded`, `failed`, `cancelled`, or `superseded`. |
| `git_commit` | Producer repo commit used for the run. |
| `git_dirty` | Boolean; production-ready manifests must normally be `false`. |
| `config_refs` | Reviewed config ids, files, or registry keys. No secret values. |
| `input_artifact_refs` | Input artifact ids/refs. Empty list is allowed only for source acquisition. |
| `output_artifact_refs` | Output artifact ids/refs. Failed runs may be empty. |
| `validation_checks` | Array of named checks with status and evidence refs. |
| `ready_signal_policy` | Whether a ready signal may be emitted from this run. |

## Optional Fields

- `task_id`: component task id when separate from request id.
- `checkpoint_ref`: latest checkpoint state for resumable segmented work.
- `provider_evidence`: sanitized endpoint/provider evidence, status codes, quotas, and retry counts.
- `failure`: structured failure class/message for failed/cancelled runs.
- `resource_summary`: row counts, bytes, elapsed time, segment counts.
- `manual_review_ref`: review/approval id when a human or reviewer agent approved a non-standard path.

## JSON Shape

```json
{
  "contract_type": "run_manifest",
  "schema_version": 1,
  "manifest_id": "mf_...",
  "request_id": "req_...",
  "run_id": "run_...",
  "producer_repo": "trading-data",
  "workflow_id": "source_04_event_overlay",
  "workflow_kind": "data_source",
  "started_at": "2026-05-08T08:00:00Z",
  "finished_at": "2026-05-08T08:04:00Z",
  "run_status": "succeeded",
  "git_commit": "...",
  "git_dirty": false,
  "config_refs": ["EQUITY_ABNORMAL_ACTIVITY_MODEL_STANDARD"],
  "input_artifact_refs": ["art_..."],
  "output_artifact_refs": ["art_..."],
  "validation_checks": [
    {"check_id": "schema_validation", "status": "passed", "evidence_ref": "art_..."}
  ],
  "ready_signal_policy": "emit_when_required_checks_pass"
}
```

## Validation Rules

- `run_status = succeeded` requires at least one passed validation check unless the workflow is explicitly reviewed as metadata-only.
- Production promotion/evaluation manifests must include no-future/leakage evidence where relevant.
- Provider/source manifests must record sanitized provider evidence and retry/segment summaries when live calls occur.
- `git_dirty = true` cannot emit a production ready signal without manual review.
- Secrets must be referenced by alias/config id only, never copied into manifests.
