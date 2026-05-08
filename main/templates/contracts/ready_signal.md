# Ready Signal Contract

## Purpose

`ready_signal_v1` is the lightweight handoff marker that tells downstream consumers a set of manifests and artifacts may be consumed under defined rules.

A ready signal is narrower than a manifest: it is not a full run log and it does not contain bulky evidence. It points to manifests and artifact refs and states readiness semantics.

## Contract Type

- **Type name:** `ready_signal_v1`
- **Owning repository:** `trading-storage`
- **Registered through:** `trading-manager/scripts/registry/`
- **Status:** Accepted template contract; production emission still requires manager/storage implementation.

## Required Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Must be `ready_signal_v1`. |
| `signal_id` | Stable signal id. |
| `signal_type` | Registered ready-signal type, e.g. `data_source_ready`, `model_eval_ready`, `promotion_review_ready`. |
| `producer_repo` | Repository that emitted the signal. |
| `workflow_id` | Workflow/source/model/script id associated with the signal. |
| `manifest_refs` | One or more `run_manifest_v1` ids/refs. |
| `artifact_refs` | One or more `artifact_ref_v1` ids/refs made consumable. |
| `ready_status` | `ready`, `partial_ready`, `not_ready`, `superseded`, or `failed`. |
| `ready_at` | UTC timestamp when the status became true. |
| `valid_after` | Earliest point-in-time timestamp at which consumers may use the payload. |
| `consumption_scope` | Intended consumers or contract scope. |
| `blocking_policy` | Consumer behavior when status is not `ready`. |

## Optional Fields

- `valid_until`: expiry timestamp for time-sensitive outputs.
- `supersedes_signal_id`: signal that this one replaces.
- `partial_reason`: why the signal is partial.
- `failure_ref`: failure/alert reference for failed or not-ready signals.
- `compatibility`: contract/schema versions that consumers must support.

## JSON Shape

```json
{
  "contract_version": "ready_signal_v1",
  "signal_id": "rsig_...",
  "signal_type": "data_source_ready",
  "producer_repo": "trading-data",
  "workflow_id": "source_03_target_state",
  "manifest_refs": ["mf_..."],
  "artifact_refs": ["art_..."],
  "ready_status": "ready",
  "ready_at": "2026-05-08T08:05:00Z",
  "valid_after": "2026-05-08T08:05:00Z",
  "consumption_scope": "trading-model;feature_03_target_state_vector",
  "blocking_policy": "consumers_must_wait_or_reject_when_not_ready"
}
```

## Consumer Rules

- Consumers must reject or wait on `not_ready`, `failed`, unknown, or expired signals.
- `partial_ready` may be consumed only by workflows that explicitly allow partial input coverage.
- A ready signal cannot make fixture/local artifacts production-ready.
- A ready signal must not override failed validation checks in the referenced manifest.
- Superseded signals must not be used for new production decisions.
