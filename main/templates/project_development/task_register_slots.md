# Task Register Slots

Formal machine-readable task-register schema is not fixed in this template yet.

If a project formalizes it, align field names with `trading-main/scripts/`.
If the register records `task_lifecycle_state`, use the default registry-registered vocabulary unless the project docs define an override.
Until then, record only the minimum task state the project actually uses.

## Example Minimal Task-State Record

```json
{
  "task_identity": "task_register_status_vocab",
  "task_lifecycle_state": "ready_to_dispatch"
}
```
