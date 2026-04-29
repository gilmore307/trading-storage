# Completion Receipt Slots

Use these canonical slot names when a project writes a formal completion receipt.
This template standardizes slot concepts and field names, not one mandatory JSON wrapper.

Exact JSON nesting and path naming remain project-defined unless the project documents them explicitly.
Reuse the default registry-registered vocabularies for `task_lifecycle_state`, `review_readiness`, and `test_status` unless the project docs define an override.

## Required Slots

- `TASK_IDENTITY` (`task_identity`) — stable identity for the completed task
- `WORKFLOW_IDENTITY` (`workflow_identity`) — workflow identity that owns the task
- `CHANGE_SUMMARY` (`change_summary`) — short summary of what changed
- `CHANGED_FILES` (`changed_files`) — changed file list
- `COMMAND_LIST` (`command_list`) — commands Codex ran
- `TEST_STATUS` (`test_status`) — summary test status reported by Codex
- `TEST_OUTPUT` (`test_output`) — test output or concise test evidence
- `ISSUE_LIST` (`issue_list`) — issues, blockers, or known gaps
- `REVIEW_READINESS` (`review_readiness`) — whether Codex reports the task ready for OpenClaw review

## Optional Slots

- `TASK_LIFECYCLE_STATE` (`task_lifecycle_state`) — task state label when the project records one in the receipt
- `TEMPORARY_NEW_NAMES` (`temporary_new_names`) — temporary names introduced during execution, when applicable
- `OUTPUT_REFERENCE` (`output_reference`) — output path or artifact reference when applicable

## Default Vocabularies

- `task_lifecycle_state`: `designing`, `ready_to_dispatch`, `dispatched`, `executing`, `blocked`, `ready_for_acceptance`, `accepted`, `rejected`, `closed`, `cancelled`
- `review_readiness`: `ready`, `not_ready`, `blocked`
- `test_status`: `passed`, `failed`, `not_run`, `partially_run`, `not_required`

## Example JSON

```json
{
  "task_identity": "task_register_status_vocab",
  "workflow_identity": "skill_cleanup",
  "task_lifecycle_state": "ready_for_acceptance",
  "change_summary": "Registered default status vocabularies and updated the skill templates.",
  "changed_files": [
    "skills/openclaw/project_development/templates/completion_receipt_slots.md",
    "skills/openclaw/project_development/references/status-vocabularies.md"
  ],
  "command_list": [
    "git status --short",
    "node --test helpers/registry/registry-reader.test.js"
  ],
  "test_status": "passed",
  "test_output": "13/13 registry helper tests passed.",
  "issue_list": [],
  "review_readiness": "ready"
}
```

## Notes

- Reuse previously ratified shared slots from `trading-main/scripts/` where they fit.
- Codex may report readiness or not-readiness, but must not report final acceptance or rejection.
