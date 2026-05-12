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
- Shared names and contracts must route through `trading-manager`.
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
- Shared names and contracts must route through `trading-manager`.
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
- Shared names and contracts must route through `trading-manager`.
- Generated outputs and secrets must stay out of Git.


## D004 - Storage owns data task SQL destinations and completion receipts

Date: 2026-04-26

### Context

Historical data tasks will be initiated by the `trading-manager` control plane and executed by `trading-data`, but durable outputs and completion evidence need storage-owned contracts.

### Decision

`trading-data` development outputs may first live in local disposable staging. `trading-storage` will own the SQL table/partition contract for historical data task outputs and the durable schema/location for data task completion receipts once durable storage implementation begins.

### Rationale

Persistence, retention, backup, restore, and reference stability belong to storage; provider semantics and row normalization belong to data.

### Consequences

- Development staging files in data-production repositories are disposable and outside durable storage responsibility.
- Exact SQL destination and receipt schemas remain pending contract work.
- Storage does not perform provider calls or task lifecycle orchestration.
- Completion receipt references become lifecycle evidence for the `trading-manager` control plane.


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

`trading-manager/storage/` held reusable templates and shared static files, but `trading-manager` should keep global registry/guidance responsibility instead of owning checked-in storage assets directly.

### Decision

Move those assets into `trading-storage/main/`.

This includes:

- `main/templates/` for reusable drafting and implementation templates.
- `main/shared/` for reviewed shared static files such as `market_regime_etf_universe.csv`.

### Consequences

- `trading-manager/storage/` is retired.
- Cross-repository references should use `trading-storage/main/...` paths.
- Shared names and template-introduced vocabulary still route through the `trading-manager` SQL registry before cross-repository use.
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
- `feature_02_sector_context` emits `bkch_bitw` as a Layer 2 candidate-comparison row.
- Future combinations involving `sector_observation_etf` candidates should default to Layer 2 unless explicitly reviewed as broad market/cross-asset evidence.


## D010 - Storage preserves compact numeric layer field names

Date: 2026-05-03
Status: Accepted

Storage contracts should preserve the canonical layer-owned field names accepted by `trading-manager` and `trading-model`. For model-layer fields this means compact numeric prefixes such as `1_*` and `2_*` in physical SQL columns as well as docs/model-facing payloads.

SQL DDL should quote numeric-leading identifiers where required instead of inventing semantic aliases such as `layer01_*` or `layer02_*`. Generic identity, lineage, timestamp, and receipt/run metadata columns may remain generic.

Storage owns durability, availability, row keys, retention, restore, and receipt boundaries; it does not decide model semantics or promote explainability/diagnostics fields into downstream contracts.

## D011 - V1 handoff contracts are accepted as storage templates

Date: 2026-05-08
Status: Accepted

### Context

The model stack and data-source/model-input design phase are closed. Remaining non-production work can now define cross-repository handoff contracts without waiting for accumulated production data.

### Decision

Accept four storage-owned V1 template contracts under `main/templates/contracts/`:

- `manager_request_v1` for manager-issued work intent.
- `run_manifest_v1` for run evidence.
- `artifact_ref_v1` for immutable output references.
- `ready_signal_v1` for downstream consumability markers.

These contracts define logical shape, required fields, mutability, readiness, and secret-handling rules. They do not by themselves implement production queues, SQL persistence, or artifact storage.

### Consequences

- `trading-manager` may register these type names and use them as control-plane vocabulary.
- Future storage implementation should persist these shapes rather than reviving older local completion-receipt-only drafts as final contracts.
- Ignored local `storage/` paths remain development evidence only and must not become production handoff locators.
- Production use still requires physical SQL/storage implementation, retention/backup/restore policy, and verified manager orchestration.

## D012 - Initial storage-contract phase was closed

Date: 2026-05-09
Status: Accepted

### Context

`trading-storage` now has a clear repository boundary, checked-in reusable non-code assets under `main/`, accepted V1 handoff templates, and the first storage-owned helper for writing completion receipt payload artifacts.

### Decision

Close the initial storage-contract-and-first-helper phase. `docs/90_storage_closeout.md` was the authoritative closeout receipt for that slice; D013 extends the closeout with local lifecycle maintenance.

At that point, no active storage-phase tasks remained. Future production storage work was deferred until a concrete manager/component consumer required it: production object-store backend policy, durable SQL partitioning, development-to-durable promotion automation, storage-resident lifecycle mutation, or high-volume artifact retention/backup/restore mechanics.

### Consequences

- `trading-storage` remains the persistence contract and payload-durability owner.
- This closeout does not enable provider calls, manager dispatch, model activation, broker execution, production object-store infrastructure, or universal SQL partitioning.
- New storage implementation should start from the accepted V1 handoff contracts and a specific consumer acceptance gate.

## D013 - Local storage lifecycle is conservative and reviewable

Date: 2026-05-09
Status: Accepted

### Context

The repository had clean Git boundaries, but local runtime files still relied only on broad `.gitignore` rules and deferred production-storage wording. That was not enough: temporary files, logs, run staging, and local artifacts need an explicit first-principles lifecycle before formal runs begin.

### Decision

Accept `docs/04_storage_lifecycle.md` as the local lifecycle contract and add the first storage-owned lifecycle helper:

- `src/trading_storage/lifecycle.py`
- `scripts/lifecycle/maintain_local_storage.py`
- `main/templates/maintenance/` timer templates

The helper dry-runs by default. It retains `storage/artifacts/`, archives `logs/`, `runs/`, and `outputs/` before removing active copies, deletes old `tmp/` files without archive, removes Python/tool caches, prunes aged local archives, keeps archive destinations under the repository root, and skips symlinks.

### Consequences

- Local ignored files now have explicit retention behavior instead of relying on ad hoc cleanup.
- Timer templates may be reviewed and installed later, but this repository change does not enable host-level scheduling by itself.
- Production object-store policy, SQL partitioning, backup/restore infrastructure, and manager-coordinated lifecycle mutation remain separate production-phase work.

## D014 - Storage lifecycle V0.1 design is accepted

Date: 2026-05-10
Status: Accepted

### Context

Historical training will produce model artifacts, source data, feature/evaluation detail, SQL partitions, logs, and intermediate files across multiple repositories. Disk pressure must be handled without breaking audit, rollback, rebuild, or point-in-time evidence. Deletion, compression, and archive operations are dangerous enough that they need storage-owned policy, dependency checks, manifests, and receipts.

### Decision

Accept the V0.1 storage lifecycle design:

- `trading-manager` owns the unified lifecycle request/task-summary surface so storage maintenance is visible and prioritized beside data/model work.
- `trading-storage` owns artifact index, dependency graph, protected-set builder, lifecycle state, retention policy, compression/archive/restore manifests, cleanup planning, lifecycle receipts, tombstones, and future lifecycle daemon.
- Promoted model bodies, including old promoted model bodies, are permanently preserved.
- Regenerable intermediate training data may be deleted after TTL when protected-set checks and quarantine rules pass.
- Downloaded source data is compressed before deletion unless explicitly classified as disposable cache; PIT, vintage, provider-window-limited, expensive, shared, or lineage-referenced source data is retained or compressed by default.
- SQL detail is archived through dump/export + compression + checksum + restore smoke. Live PostgreSQL data files are never compressed directly.
- Lifecycle states include `hot`, `warm`, `cold_compressible`, `cold_compressed`, `archivable`, `archived`, `delete_candidate`, `quarantined_for_delete`, `deleted`, and `restored`.
- Deletion and SQL detach/drop require quarantine and a final protected-set recheck.
- Lifecycle rules should be declarative policy, not hidden script branches.
- Every compression, archive, deletion, and restore action must emit receipt evidence; deleted artifacts retain tombstones.

### Consequences

- The existing local ignored-file helper remains valid, but production lifecycle mutation is not authorized until artifact index, protected-set builder, lifecycle planner, receipt writing, and restore verification are implemented and reviewed.
- `trading-manager` may register lifecycle contract/type names and request/prioritize/schedule/observe lifecycle work through the unified manager task system, but it must not directly delete files, compress SQL, or mutate storage paths.
- `trading-data` and `trading-model` should add artifact metadata needed by storage lifecycle classification, including artifact kind, reproducibility class, lineage refs, source/model version refs, and recommended retention class.


## D015 - Dashboard summary read models live in storage

Date: 2026-05-12
Status: Accepted

### Context

`trading-dashboard` is being designed as an owner-facing summary surface, not an internal maintenance console. Chentong clarified that dashboard summary/read-model outputs should live in the storage repository.

### Decision

Accept `trading-storage` as the durable/materialized home for dashboard summary/read-model outputs. Storage owns physical placement, retention, backup, restore, archive, materialized snapshot history, and lifecycle treatment for these summaries.

Semantic ownership stays with the upstream domain owner: `trading-manager` owns task/scheduler/promotion summary semantics, `trading-model` owns model metric semantics, `trading-execution` owns realtime/execution summary semantics, `trading-data` owns provider/data summary semantics, and `trading-storage` owns persistence/lifecycle and storage-health summary semantics.

### Consequences

- Dashboard reads storage-hosted summaries instead of raw internal component tables.
- `docs/96_dashboard_read_models.md` owns the storage-side design boundary.
- This decision does not create physical tables, object paths, refresh jobs, or lifecycle mutation.
- Shared summary contract names must be registered through `trading-manager` before implementation depends on them across repositories.


## D016 - Durable non-SQL saved data belongs in storage

Date: 2026-05-12
Status: Accepted

### Context

The trading system now produces multiple classes of saved data that are not naturally stored as live SQL rows: JSON/JSONL/CSV/parquet payloads, manifests, receipts, model bodies, dashboard summaries, archives, tombstones, restore manifests, and other object-like evidence. If these files remain scattered across component repositories, the platform will lose clear retention, backup, restore, lifecycle, and reference ownership.

### Decision

All durable, system-owned non-SQL saved data belongs under `trading-storage` contracts and storage-owned locations by default. Component repositories may still create disposable ignored local staging during development or execution, but accepted durable non-SQL outputs should be promoted/written/referenced through storage-owned paths or future object/SQL-backed storage contracts.

This rule does not move semantic ownership. Producing repositories still own output meaning, validation, row/content semantics, and generation logic. `trading-storage` owns physical placement, references, retention, backup, restore, archive, lifecycle policy, tombstones, and restore evidence.

Accepted exceptions are source code, tests, docs, checked-in templates, reviewed shared static files, registry exports, approved secret storage outside repositories, disposable caches, and explicitly non-durable local staging. SQL-resident rows/tables remain governed by SQL storage contracts rather than this non-SQL file/object rule.

### Consequences

- New durable file/object-style artifacts should not be normalized into component-local saved directories as their final home.
- Future implementation slices must define concrete storage paths/object layouts, index entries, protected-set behavior, retention classes, and restore evidence before broad migration.
- Dashboard summaries, completion receipts, model bodies, manifests, archives, tombstones, and restore manifests are storage-owned durable data unless a narrower accepted contract says otherwise.
- Component-local runtime files remain acceptable only as disposable, ignored, reproducible, or not-yet-promoted staging.
- Shared contract names and new durable artifact classes still route through `trading-manager` registry before cross-repository implementation depends on them.
