# Maintenance Output Slots

Use these canonical slot names when a project writes a formal maintenance output.
This template standardizes slot concepts and field names, not one mandatory JSON wrapper.

Exact JSON nesting, path naming, and retention remain project-defined unless the project documents them explicitly.
When task states are summarized, reuse the default registry-registered vocabularies for `task_lifecycle_state`, `maintenance_status`, and `docs_status` unless the project docs define an override.

## Required Slots

- `REPOSITORY_PATH` (`repository_path`) — repository root path for the project being checked
- `MAINTENANCE_STATUS` (`maintenance_status`) — overall maintenance result or status summary
- `CHECK_TIME` (`check_time`) — time the maintenance check ran
- `DOCS_STATUS` (`docs_status`) — docs condition summary
- `TASK_STATUS_SUMMARY` (`task_status_summary`) — grouped task-state summary
- `PENDING_DISPATCH_LIST` (`pending_dispatch_list`) — tasks ready or waiting to dispatch
- `PENDING_ACCEPTANCE_LIST` (`pending_acceptance_list`) — tasks waiting for acceptance review
- `BLOCKED_TASK_LIST` (`blocked_task_list`) — blocked tasks that still need attention
- `DICTIONARY_ISSUE_LIST` (`dictionary_issue_list`) — naming or registry-governance issues found during maintenance
- `SPLIT_ISSUE_LIST` (`split_issue_list`) — file or module split-discipline issues found during maintenance
- `MEMORY_ROUTE_ISSUE_LIST` (`memory_route_issue_list`) — project-memory routing issues found during maintenance
- `FOLLOW_UP_TASK_LIST` (`follow_up_task_list`) — follow-up tasks created or needed from maintenance
- `MAINTENANCE_SUMMARY` (`maintenance_summary`) — concise maintenance summary

## Example JSON

```json
{
  "repository_path": "/root/projects/network-framework",
  "maintenance_status": "needs_attention",
  "check_time": "2026-04-24T15:45:00Z",
  "docs_status": "drifted",
  "task_status_summary": {
    "ready_to_dispatch": 1,
    "executing": 2,
    "blocked": 1,
    "ready_for_acceptance": 1
  },
  "pending_dispatch_list": [
    "task_docs_spine_cleanup"
  ],
  "pending_acceptance_list": [
    "task_register_status_vocab"
  ],
  "blocked_task_list": [
    "task_configure_repo_remote"
  ],
  "dictionary_issue_list": [],
  "split_issue_list": [],
  "memory_route_issue_list": [
    "Move implementation notes from chat into docs/05_decision.md."
  ],
  "follow_up_task_list": [
    "task_reconcile_docs_drift"
  ],
  "maintenance_summary": "Docs drift remains and one task is blocked on missing remote configuration."
}
```

## Notes

- Reuse previously ratified shared slots from `trading-main/scripts/` where they fit.
- `maintenance_status`: `healthy`, `needs_attention`, `blocked`
- `docs_status`: `aligned`, `drifted`, `blocked`
- Report only maintenance findings the project can state concretely.
