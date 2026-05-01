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

Historical data tasks will be initiated by the `trading-main` control plane and executed by `trading-data`, but durable outputs and completion evidence need storage-owned contracts.

### Decision

`trading-data` development outputs may first live in local disposable staging. `trading-storage` will own the SQL table/partition contract for historical data task outputs and the durable schema/location for data task completion receipts once durable storage implementation begins.

### Rationale

Persistence, retention, backup, restore, and reference stability belong to storage; provider semantics and row normalization belong to data.

### Consequences

- Development staging files in data-production repositories are disposable and outside durable storage responsibility.
- Exact SQL destination and receipt schemas remain pending contract work.
- Storage does not perform provider calls or task lifecycle orchestration.
- Completion receipt references become lifecycle evidence for the `trading-main` control plane.


## D005 - Development data files are outside durable storage responsibility

Date: 2026-04-26

### Context

The user previously clarified that early development-stage data-production outputs may be local files rather than SQL rows; accepted formal source/feature/model outputs now prefer SQL contracts.

### Decision

Treat local data-production staging as disposable, not durable storage. `trading-storage` will define promotion, SQL destination, receipt storage, retention, and backup/restore contracts later.

### Rationale

This prevents early schema experiments from polluting databases while keeping durable storage boundaries clean.

### Consequences

- Storage implementation should not assume development files are durable.
- SQL contracts remain future work.
- A promotion rule is required before development outputs become durable system data.


## D006 - Completion receipts contain per-run evidence

Date: 2026-04-26

### Context

The user clarified that one data task may have multiple scheduled or periodic runs.

### Decision

Treat data task completion receipts as task-level files that contain `runs[]` entries. Each run entry records per-run status, timestamps, outputs, row counts, and error.

### Rationale

This preserves one stable task definition while allowing durable storage contracts later to track every invocation.

### Consequences

- Receipt storage design should support appending/updating run entries.
- Run ids and task ids are distinct.
- Durable receipt schemas remain future contract work.

## D007 - Nested final artifacts use SQL JSONB as the durable canonical body

Date: 2026-04-27

### Context

Some `trading-data` source outputs are naturally nested point-in-time artifacts rather than flat row series. `option_chain_snapshot` is the first concrete example: one logical artifact contains many option contracts and nested quote, IV, Greeks, derived, and underlying context.

### Decision

For nested final artifacts such as `option_chain_snapshot`, the durable SQL contract should store the complete normalized artifact in a PostgreSQL `jsonb` column inside the SQL table row. Development-stage files may remain local disposable JSON until durable storage contracts are implemented.

### Rationale

SQL JSONB keeps the full final artifact in transactional database storage, avoiding external file-path indirection while preserving the nested structure needed by downstream model inputs. It also leaves room for later SQL projections without making the first durable contract over-fragmented.

### Consequences

- The SQL row, not an external JSON file path, owns the canonical durable nested artifact body.
- Projection tables, indexes, or materialized views may be added later for query speed, but they should be derived from the canonical JSONB body unless a later decision changes ownership.
- Durable writes for one nested artifact should be transactional: failed writes must not leave partial final artifacts.
- `trading-storage` still owns the exact table, partition, retention, backup, restore, and receipt contract before production use.

## D008 - Shared non-code assets live under main

Date: 2026-04-29
Status: Accepted

### Context

`trading-main/storage/` held reusable templates and shared static files, but `trading-main` should keep global registry/guidance responsibility instead of owning checked-in storage assets directly.

### Decision

Move those assets into `trading-storage/main/`.

This includes:

- `main/templates/` for reusable drafting and implementation templates.
- `main/shared/` for reviewed shared static files such as `market_regime_etf_universe.csv`.

### Consequences

- `trading-main/storage/` is retired.
- Cross-repository references should use `trading-storage/main/...` paths.
- Shared names and template-introduced vocabulary still route through the `trading-main` SQL registry before cross-repository use.
- Generated outputs, runtime artifacts, logs, notebooks, caches, and secrets remain out of Git.

## D009 - Sector-observation combinations belong to Layer 2

Date: 2026-04-30
Status: Accepted

### Context

The shared relative-strength combination table drives both Layer 1 broad market-state evidence and Layer 2 sector/industry candidate evidence. Chentong accepted the stricter boundary that all sector/industry rotation-related evidence should move to Layer 2 so Layer 1 stays clean. The `bkch_bitw` pair uses `BKCH`, a `sector_observation_etf`, but was still marked as `primary`, which caused crypto-related equity candidate/theme leadership evidence to remain in Layer 1.

### Decision

Classify `bkch_bitw` as `sector_rotation` instead of `primary`.

### Consequences

- `feature_01_market_regime` no longer generates `bkch_bitw_*` Layer 1 payload keys.
- `feature_02_security_selection` emits `bkch_bitw` as a Layer 2 candidate-comparison row.
- Future combinations involving `sector_observation_etf` candidates should default to Layer 2 unless explicitly reviewed as broad market/cross-asset evidence.
