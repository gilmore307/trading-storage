# Acceptance Receipt Slots

Use these canonical slot names when a project writes a formal acceptance receipt.
This template standardizes slot concepts and field names, not one mandatory JSON wrapper.

Exact JSON nesting and path naming remain project-defined unless the project documents them explicitly.
Reuse the default registry-registered vocabularies for `acceptance_outcome` and `test_status` unless the project docs define an override.

## Required Slots

- `TASK_IDENTITY` (`task_identity`) — stable identity for the reviewed task
- `WORKFLOW_IDENTITY` (`workflow_identity`) — workflow identity that owns the task
- `ACCEPTANCE_OUTCOME` (`acceptance_outcome`) — OpenClaw review outcome for the task
- `ACCEPTANCE_REFERENCE` (`acceptance_reference`) — file, path, or section used as the acceptance basis
- `REVIEWED_FILES` (`reviewed_files`) — files reviewed during acceptance
- `REVIEWED_COMMANDS` (`reviewed_commands`) — commands reviewed during acceptance
- `TEST_STATUS` (`test_status`) — summary test status used in the review
- `TEST_OUTPUT` (`test_output`) — test output or concise test evidence used in the review
- `ISSUE_LIST` (`issue_list`) — remaining issues, rejection reasons, or follow-up concerns
- `ACCEPTANCE_SUMMARY` (`acceptance_summary`) — concise acceptance decision summary

## Optional Slots

- `DECISION_REFERENCES` (`decision_references`) — related decision records when relevant
- `NEXT_TASK_REFERENCE` (`next_task_reference`) — next linked task when follow-up work is needed

## Default Vocabularies

- `acceptance_outcome`: `accepted`, `rejected`, `returned`, `blocked`
- `test_status`: `passed`, `failed`, `not_run`, `partially_run`, `not_required`

## Example JSON

```json
{
  "task_identity": "task_register_status_vocab",
  "workflow_identity": "skill_cleanup",
  "acceptance_outcome": "accepted",
  "acceptance_reference": "docs/03_acceptance.md#status-vocabulary-cleanup",
  "reviewed_files": [
    "skills/openclaw/project_development/templates/acceptance_receipt_slots.md",
    "skills/openclaw/project_development/templates/maintenance_output_slots.md"
  ],
  "reviewed_commands": [
    "git diff --stat",
    "node --test helpers/registry/registry-reader.test.js"
  ],
  "test_status": "passed",
  "test_output": "13/13 registry helper tests passed.",
  "issue_list": [],
  "acceptance_summary": "Accepted after template review and registry verification."
}
```

## Notes

- Reuse previously ratified shared slots from `trading-main/scripts/` where they fit.
- Only OpenClaw writes the acceptance receipt and final acceptance outcome.
