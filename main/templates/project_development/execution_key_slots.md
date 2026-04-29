# Execution Key Slots

Use these canonical slot names when a project writes a formal execution key.
This template standardizes slot concepts and field names, not one mandatory JSON wrapper.

Exact JSON nesting and path naming remain project-defined unless the project documents them explicitly.
If the project also records `task_lifecycle_state` or `test_status`, reuse the default registry-registered vocabularies unless the project docs define an override.

## Required Slots

- `TASK_IDENTITY` (`task_identity`) — stable identity for the dispatched task
- `WORKFLOW_IDENTITY` (`workflow_identity`) — workflow identity that owns the task
- `REPOSITORY_PATH` (`repository_path`) — repository root path for the task
- `TASK_GOAL` (`task_goal`) — one clear goal for the task
- `TASK_SCOPE` (`task_scope`) — bounded scope statement for the task
- `ACCEPTANCE_REFERENCE` (`acceptance_reference`) — file, path, or section defining acceptance
- `ALLOWED_PATHS` (`allowed_paths`) — paths Codex may edit
- `BLOCKED_PATHS` (`blocked_paths`) — paths Codex must not edit
- `TEST_EXPECTATION` (`test_expectation`) — required test expectation or explicit reason tests are not required
- `EXPECTED_OUTPUT` (`expected_output`) — expected artifact or response from execution
- `CONSTRAINTS` (`constraints`) — non-negotiable task constraints
- `COMPLETION_RECEIPT_REFERENCE` (`completion_receipt_reference`) — where the completion report should be returned or anchored

## Optional Slots

- `DECISION_REFERENCES` (`decision_references`) — related decision records when relevant
- `TEST_COMMANDS` (`test_commands`) — concrete commands to run when they are known
- `OUTPUT_REFERENCE` (`output_reference`) — output path or artifact reference when a separate output target exists

## Notes

- Register or reuse these field names in `trading-main/scripts/`.
- Include naming guidance in the task package or constraints when the task may require new names.
