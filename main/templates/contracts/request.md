# Request Contract

## Purpose

`manager_request_v1` is the durable cross-repository request contract. It records intended work issued by `trading-manager`, a human, or an approved agent into a target repository.

Requests are intent records. They do not prove a run completed; completion is recorded by `run_manifest_v1` and made consumable by `ready_signal_v1`.

## Contract Type

- **Type name:** `manager_request_v1`
- **Owning repository:** `trading-storage`
- **Registered through:** `trading-manager/scripts/registry/`
- **Status:** Accepted template contract; production queue/storage implementation still requires manager/storage work.

## Required Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Must be `manager_request_v1`. |
| `request_id` | Stable request id. |
| `idempotency_key` | Key used to prevent duplicate execution. |
| `requester` | `trading-manager`, human reviewer id, or approved agent id. |
| `target_repo` | Repository expected to execute the request. |
| `target_workflow` | Stable script/source/model/workflow key. |
| `request_type` | Registered or reviewed request type. |
| `production_mode` | `development`, `dry_run`, `paper`, or `production`. |
| `priority` | `low`, `normal`, `high`, or `urgent`. |
| `created_at` | UTC creation timestamp. |
| `not_before` | Earliest execution time. |
| `parameters` | Workflow parameters. Must not include secrets. |
| `input_artifact_refs` | Input artifact refs if any. |
| `expected_output_types` | Expected artifact/manifest/ready-signal types. |
| `live_call_policy` | Provider/broker/network call policy. |
| `retry_policy` | Retry and backoff constraints. |
| `cancellation_policy` | How cancellation/supersession is handled. |

## Optional Fields

- `deadline_at`: desired completion deadline.
- `schedule_ref`: recurring schedule reference.
- `manual_approval_ref`: approval ticket/id for production or unusual live calls.
- `resource_limits`: row/window/rate/time limits.
- `checkpoint_policy`: segment/checkpoint behavior for resumable work.
- `review_requirements`: required post-run review gates.

## JSON Shape

```json
{
  "contract_version": "manager_request_v1",
  "request_id": "req_...",
  "idempotency_key": "source_04_event_overlay:ABC:2026-05-08",
  "requester": "trading-manager",
  "target_repo": "trading-data",
  "target_workflow": "source_04_event_overlay",
  "request_type": "data_source_run",
  "production_mode": "dry_run",
  "priority": "normal",
  "created_at": "2026-05-08T08:00:00Z",
  "not_before": "2026-05-08T08:00:00Z",
  "parameters": {"symbol": "ABC", "timeframe": "1Min"},
  "input_artifact_refs": ["art_..."],
  "expected_output_types": ["run_manifest_v1", "artifact_ref_v1", "ready_signal_v1"],
  "live_call_policy": {
    "allow_live_calls": false,
    "allowed_providers": [],
    "max_requests": 0
  },
  "retry_policy": {
    "max_attempts": 0,
    "backoff": "none"
  },
  "cancellation_policy": "idempotent_cancel_before_start"
}
```

## Rules

- `production_mode = production` must require explicit approval and reviewed live-call policy.
- Live provider calls must be disabled by default unless the request explicitly permits them.
- Secrets must be passed as registry/config aliases only.
- Duplicate idempotency keys must not create duplicate production effects.
- A superseded request must not emit a new production ready signal unless a reviewed replacement request authorizes it.
