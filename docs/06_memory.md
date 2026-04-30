# Memory

## Durable Local Notes

- `trading-storage` owns its component boundary only; do not let it absorb neighboring repository responsibilities.
- Generated outputs, logs, notebooks, credentials, and secrets must stay out of Git.
- Shared fields, statuses, type values, helper surfaces, and reusable templates discovered here must be routed to `trading-main` for registry/docs review.
- Durable storage layout and retention are owned by `trading-storage` unless this repository is defining those storage contracts.
- Component runtime dependencies should use the shared `trading-main` environment policy unless an exception is accepted.
- For historical `trading-data` tasks, development outputs/receipts may live in local disposable staging. Storage should own later SQL output destination contracts and durable completion receipt storage/reference formats; it must not own provider semantics or manager lifecycle.
- Data task completion receipts should be task-level records with nested `runs[]` entries for each scheduled/periodic invocation.
