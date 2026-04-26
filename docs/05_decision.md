# Decision


## D001 - Storage owns persistence policy, not artifact semantics

Date: 2026-04-25

### Context

The trading platform needs `trading-storage` to have a clear owner boundary before implementation begins.

### Decision

Storage defines where and how durable outputs live; producing repositories still own the semantic contents of their artifacts.

### Rationale

A narrow component boundary prevents hidden coupling and keeps cross-repository work reviewable.

### Consequences

- Implementation work must stay inside the accepted component role.
- Shared names and contracts must route through `trading-main`.
- Generated outputs and secrets must stay out of Git.


## D002 - Generated artifacts stay out of Git

Date: 2026-04-25

### Context

The trading platform needs `trading-storage` to have a clear owner boundary before implementation begins.

### Decision

Runtime data, artifacts, archives, and backups must not be committed to the repository.

### Rationale

A narrow component boundary prevents hidden coupling and keeps cross-repository work reviewable.

### Consequences

- Implementation work must stay inside the accepted component role.
- Shared names and contracts must route through `trading-main`.
- Generated outputs and secrets must stay out of Git.


## D003 - Restore expectations are first-class

Date: 2026-04-25

### Context

The trading platform needs `trading-storage` to have a clear owner boundary before implementation begins.

### Decision

Backup, restore, archive, and rehydrate policy must be defined before storage becomes critical infrastructure.

### Rationale

A narrow component boundary prevents hidden coupling and keeps cross-repository work reviewable.

### Consequences

- Implementation work must stay inside the accepted component role.
- Shared names and contracts must route through `trading-main`.
- Generated outputs and secrets must stay out of Git.


## D004 - Storage owns data task SQL destinations and completion receipts

Date: 2026-04-26

### Context

Historical data tasks will be initiated by `trading-manager` and executed by `trading-data`, but durable outputs and completion evidence need storage-owned contracts.

### Decision

`trading-data` development outputs first live under local `trading-data/data/storage/`. `trading-storage` will own the SQL table/partition contract for historical data task outputs and the durable schema/location for data task completion receipts once durable storage implementation begins.

### Rationale

Persistence, retention, backup, restore, and reference stability belong to storage; provider semantics and row normalization belong to data.

### Consequences

- Development files under `trading-data/data/storage/` are disposable and outside durable storage responsibility.
- Exact SQL destination and receipt schemas remain pending contract work.
- Storage does not perform provider calls or task lifecycle orchestration.
- Completion receipt references become lifecycle evidence for `trading-manager`.


## D005 - Development data files are outside durable storage responsibility

Date: 2026-04-26

### Context

The user clarified that development-stage `trading-data` outputs should be local files rather than SQL rows.

### Decision

Treat `trading-data/data/storage/` as disposable development staging owned by `trading-data`, not durable storage. `trading-storage` will define promotion, SQL destination, receipt storage, retention, and backup/restore contracts later.

### Rationale

This prevents early schema experiments from polluting databases while keeping durable storage boundaries clean.

### Consequences

- Storage implementation should not assume development files are durable.
- SQL contracts remain future work.
- A promotion rule is required before development outputs become durable system data.
