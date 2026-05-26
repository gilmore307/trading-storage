# Storage Lifecycle Policy

Status: V0.1 dry-run planner, quarantine/recheck evidence, execution scaffold, narrow single-file compression executor, reviewed file-backed SQL archive executor, archive restore verifier, no-mutation quarantine/delete receipt builder, and one-pass safe file-lifecycle acceptance available; destructive mutation executors remain deferred

## Purpose

`trading-storage` owns lifecycle maintenance for durable trading artifacts, source data, model artifacts, SQL archives, local files, restore metadata, and deletion evidence.

The policy goal is not merely to free disk space. The goal is to make compression, archiving, restore, and deletion auditable lifecycle operations with dependency checks and receipts.

Core rule:

```text
Layer 1 and Layer 2 data are persistent source/feature foundations and must be retained, compressed, and protected from deletion by default.
Reusable source data, including Layer 1/2 market-regime and sector-context foundations, is never a fold-completion delete target.
Target-specific or experiment-specific source data that will not be reused may enter deletion planning only as an explicit fold-scoped folder after the full Layer 1-10 fold closes.
Later-layer model-run metadata and dashboard/cache snapshots may be deleted only after the model run cycle closes, provided latest summaries, receipts, manifests, lineage refs, unresolved-alert evidence, and any needed regeneration/debug evidence remain. While the event model is being redesigned and downstream models must be regenerated, dashboard/model-run metadata pruning is on hold.
Promoted model bodies are preserved permanently.
Regenerable intermediate training data may be deleted after TTL.
Downloaded source data is compressed before deletion and deleted only when safely reproducible and unreferenced.
SQL detail is partition/table archived through export + compression; live database files are never compressed directly.
Every compression, archive, delete, and restore action writes manifest/receipt evidence.
```

## Repository responsibilities

### trading-manager

Owns the unified control-plane view for lifecycle maintenance: lifecycle requests, priorities, deadlines, task summary visibility, scheduling intent, run/artifact/ready refs, workflow state, promotion/review decisions, and lifecycle request routing. Storage lifecycle work should enter normal operation through `manager_request`/`storage_lifecycle_request` so it is visible beside data/model tasks.

Manager may request, prioritize, schedule, and observe storage lifecycle work, but it does not delete files, compress SQL, mutate storage paths, choose physical storage actions by itself, or bypass storage protected-set checks.

### trading-data

Owns source acquisition, normalization, and feature/source artifact semantics. Completion receipts should describe artifact kind, reproducibility class, source provider, source times, lineage refs, rebuild hints, and recommended retention class so storage can classify outputs safely.

### trading-model

Owns model artifacts, evaluation artifacts, promotion candidates, model versions, and model lineage. Model/evaluation/promotion artifacts should identify model id/version, dataset snapshot/split refs, feature contract refs, source refs, code version refs, and promotion/activation refs where available.

Promotion scripts may classify artifact retention intent, especially `keep_forever` for promoted model bodies and lineage, but they must not call storage cleanup, compression, archive, SQL detach/drop, or deletion executors directly. Promotion classifies artifacts; manager schedules lifecycle; storage executes lifecycle.

### trading-storage

Owns the artifact index, dependency graph, protected-set builder, lifecycle state, retention policy, compression/archive manifests, restore manifests, cleanup planning, lifecycle receipts, tombstones, and future lifecycle daemon.

## Lifecycle state machine

Storage lifecycle states are explicit:

```text
hot
warm
cold_compressible
cold_compressed
archivable
archived
delete_candidate
quarantined_for_delete
deleted
restored
```

Rules:

- `hot`: active run, active review, active downstream chain, current online query, or current promoted dependency. Do not compress, move, detach, or delete.
- `warm`: recently completed or likely to be read soon. Direct-readable compression may be allowed if it does not break consumers.
- `cold_compressible`: no active writer/reader and useful for future audit/reuse. Candidate for compression.
- `cold_compressed`: compressed copy verified; uncompressed copy may be removed only when policy allows.
- `archivable`: online detail can move to archive after protected-set and dependency checks.
- `archived`: archive exists with checksum and restore path.
- `delete_candidate`: appears safe to remove but has not completed quarantine.
- `quarantined_for_delete`: final waiting period before deletion; a second protected-set check is required.
- `deleted`: bytes removed; tombstone and deletion receipt remain.
- `restored`: restored from compressed/archive evidence; restore receipt records the operation.

Deletion and SQL detach/drop must pass through `quarantined_for_delete`. Pure compression does not require quarantine, but it does require checksum verification and a restore smoke test when the result is not directly readable.

## Artifact categories and retention intent

### Promoted model body

Includes promoted and old-promoted model artifacts, configs, schema/feature contracts, evaluation summaries, promotion decisions, activation/deactivation records, upstream lineage, and code/version refs.

Policy: preserve permanently. Do not automatically delete old promoted model bodies.

### Layer 1 and Layer 2 foundation data

Includes Layer 1 market-regime and Layer 2 sector-context source/feature foundations, plus lineage-required PIT inputs needed to rebuild downstream model runs.

Policy: persist by default. Prefer compression and archive over deletion. Do not classify Layer 1/2 data as disposable metadata merely because a model run completed.

### Layer 1 and Layer 2 intermediate/runtime files

Includes Layer 1/2 scratch, staging, intermediate files, runtime directories, failed-run temp files, and stdout/stderr/log files that are not the only remaining receipt, manifest, lineage reference, reusable source/feature foundation, or compact summary.

Policy: delete by TTL after the run or fold closes and after compact summaries, receipts, manifests, and reusable Layer 1/2 outputs are preserved. These files may enter quarantine planning even though Layer 1/2 final source/feature foundations remain protected.

### Fold-scoped target source data

Includes target-symbol or experiment-specific source folders created for a bounded six-month model-worker fold, where the folder is not intended to serve as reusable Layer 1/2 source foundation or durable replay/source history.

Policy: delete by fold folder only after the full Layer 1-10 fold closes. The accepted folder boundary is `storage/01_source_data/fold_scoped/<fold_id>/...`; storage maintenance emits `storage_fold_source_cleanup_candidate` rows only for completed fold ids under that root. These candidates still require artifact-index coverage, protected-set clearance, quarantine/recheck, and deletion receipts before any destructive executor may remove bytes. Individual files inside a fold-scoped folder should not be independently deleted out of order.

### Later-layer model-run metadata

Includes Layer 3+ diagnostic summaries, runtime metadata, dashboard snapshots, staging/intermediate files, scratch feature files, failed-run temp files, duplicated dry-run payloads, and old stdout/stderr logs that are not the only remaining receipt/manifest/lineage evidence.

Policy: delete by TTL after the model run cycle closes and after latest summaries, receipts, manifests, lineage refs, and unresolved-alert evidence are preserved. Keep only compact summary/receipt evidence after the retention window.

### Replay datasets and replay downloads

Replay storage separates reusable replay inputs, model-specific temporary downloads, and permanent model-pipeline replay results.

Reusable replay inputs include Layer 1 market-regime inputs, Layer 2 sector-context inputs, and event/news inputs collected for replay/replay use. Policy: retain or compress/archive because later model pipelines and replay windows can reuse them.

Model-specific replay downloads include one-off files pulled only because a particular model pipeline needed them for a replay run, such as point-in-time option snapshots. Policy: delete by TTL after the replay closes once result summaries, manifests, acquisition receipts, and any reusable inputs are preserved.

Model-pipeline replay result summaries are permanent. Each model pipeline must retain its compact replay result summary, scorecard/baseline comparison, manifest refs, and receipt evidence so later promotions remain comparable without keeping every non-reusable downloaded file online.

### Downloaded source data

Source data is classified by reproducibility and reuse:

- point-in-time, vintage, revision-sensitive, provider-window-limited, expensive, paid-window, option history, SEC filing snapshots, GDELT historical pulls, and lineage-referenced source data: compress and retain by default;
- Trading Economics (`trading_economics_calendar_web`, including `te_recent_calendar_refresh_*`) source data is append-only protected because the subscription is no longer available; never delete existing TE payloads, and only add new/latest data incrementally if it becomes available again;
- stable re-downloadable provider cache and one-off experiment pulls without lineage references: TTL delete may be allowed after quarantine;
- shared normalized source data: retain or compress while any active/promoted/review lineage may reference it.

Policy: source data is compressed before deletion unless the policy explicitly classifies it as disposable cache.

### SQL data

Online summary and current control-plane facts remain online. Closed row-level detail, old feature partitions, historical source partitions, and old evaluation details may be exported and compressed. SQL temporary/intermediate tables may be deleted by TTL when reproducible.

Policy: never compress PostgreSQL live data files directly. Archive through dump/export and restore smoke.

## Retention defaults

- Layer 1 market-regime data: persistent; compress/archive if needed, do not auto-delete;
- Layer 2 sector-context data: persistent; compress/archive if needed, do not auto-delete;
- Layer 1/2 intermediate/runtime/log files: TTL delete after run/fold close when summaries, receipts, manifests, and reusable outputs are retained;
- promoted model bodies: permanent;
- promotion/review/activation/deactivation receipts: permanent;
- dataset snapshot/split manifests: permanent or lineage lifetime;
- model-pipeline replay result summaries and scorecards: permanent;
- replay Layer 1/2 and event/news reusable inputs: retain or compress/archive;
- model-specific replay downloads such as one-off option snapshots: TTL delete after replay close when summaries/manifests/receipts are retained;
- PIT/vintage/source history: compress and retain by default;
- Trading Economics calendar/source payloads: keep forever; no delete candidates, no destructive pruning, only append/incremental additions;
- dashboard/read-model latest summaries: retained;
- dashboard/read-model high-frequency snapshots: count-based metadata pruning after explicit reviewed approval; current default prune plan keeps the latest 10 snapshots per contract and marks older snapshots as delete candidates while preserving `latest.json`, schemas, indexes, SQL, and source data;
- lifecycle receipts, tombstones, executed protected sets, executed lifecycle plans, and quarantine/recheck evidence: retained as audit evidence;
- lifecycle `runs`, `outputs`, and `staging`: ordinary runtime context rolls off after about 30 days; formal lifecycle evidence found there is retained until extracted to canonical `storage/90_lifecycle` evidence directories;
- Layer 3+ model-run metadata/intermediates: delete by TTL after run-cycle close when reproducible or no longer lineage-required;
- failed/blocked run scratch: 7-14 days;
- ordinary logs: 30 days, then delete or compress if important;
- unpromoted candidate intermediates: 30-60 days;
- review-candidate intermediates: review complete + 30 days;
- promoted model training intermediates: promotion + 30-90 days, then delete intermediates while retaining model body/manifests/source refs;
- SQL row-level historical detail: archive compressed after partition close and protected-set clearance;
- SQL summary/control-plane facts: remain online.

## Declarative policy

Lifecycle behavior should be driven by reviewed YAML/JSON policy records, not hidden script branches. A rule should contain at least:

```yaml
policy_id: storage_lifecycle_default
rule_id: pit_source_compress
selector:
  artifact_kind: pit_source_data
action: compress
codec: zstd
require_protected_set_clear: true
require_restore_smoke: true
delete_uncompressed_after_verify: true
```

Scripts may implement the policy, but policy review must be possible without reading every code branch.

## Current scheduled root inventory

Scheduled maintenance emits a `storage_root_inventory_summary` inside each `storage_scheduled_maintenance_summary`. This is the formal lifecycle-management view of the numbered storage layout:

- `storage/01_source_data`
- `storage/02_control_plane`
- `storage/03_model_artifacts`
- `storage/04_execution_artifacts`
- `storage/05_replay_datasets`
- `storage/06_dashboard_cache`
- `storage/90_lifecycle`

The inventory records existence, file count, directory count, byte count, lifecycle role, and managed root ids. It does not hash payloads and does not authorize mutation. Hashing, protected-set checks, compression planning, quarantine/recheck, and deletion gates remain in the artifact-index and lifecycle-plan pipeline.

Scheduled maintenance also reads completed ten-layer fold state from manager. For completed folds, it may report `storage_fold_sql_backup_candidate` rows and, when `storage/01_source_data/fold_scoped/<fold_id>/` exists, `storage_fold_source_cleanup_candidate` rows. Cleanup candidates are folder-level planning evidence only; the scheduled maintenance pass does not delete those folders.

## Current V0.1 dry-run planner

The first durable-artifact lifecycle planner is conservative and non-mutating:

- importable code: `src/trading_storage/lifecycle_planner.py`;
- executable wrapper: `scripts/lifecycle/plan_storage_lifecycle.py`;
- default input: a live bounded artifact-index scan plus a freshly built protected set;
- optional inputs: existing artifact-index JSONL, existing protected-set JSON, and reviewed JSON policy rules;
- default output behavior prints a summary only; `--write` writes `storage/90_lifecycle/plans/storage_lifecycle_plan.json` and `storage/90_lifecycle/plans/storage_lifecycle_plan_summary.json`;
- all output records carry `dry_run=true` and `mutation_performed=false` in the summary;
- protected artifacts become `retain_protected` regardless of matched lifecycle policy;
- ambiguous manual-review artifacts remain retained until metadata is classified.
- explicit `storage_retention_class` or `retention_class` metadata can classify reviewed artifacts, including `fold_complete_delete_allowed` for fold-scoped source artifacts that may become quarantine candidates after fold completion.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/plan_storage_lifecycle.py
PYTHONPATH=src python3 scripts/lifecycle/plan_storage_lifecycle.py --write
```

This planner prepares evidence for later compression/archive/quarantine executors; it does not perform lifecycle actions.

## Current V0.1 quarantine/recheck evidence

The first quarantine-before-delete evidence builder is conservative and non-mutating:

- importable code: `src/trading_storage/quarantine_recheck.py`;
- executable wrapper: `scripts/lifecycle/build_quarantine_recheck_evidence.py`;
- default input: a live dry-run lifecycle plan;
- optional inputs: existing lifecycle-plan JSON plus optional final protected-set JSON;
- default output behavior prints a summary only; `--write` writes `storage/90_lifecycle/quarantine_recheck/quarantine_recheck_evidence.json` and `storage/90_lifecycle/quarantine_recheck/quarantine_recheck_summary.json`;
- every row has `mutation_performed=false` and `deletion_allowed=false`;
- quarantine candidates without final protected-set evidence remain `dry_run_candidate_pending_recheck`;
- a clear final recheck is recorded as `dry_run_recheck_clear`, but still does not authorize deletion without a reviewed executor and deletion receipt.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/build_quarantine_recheck_evidence.py
PYTHONPATH=src python3 scripts/lifecycle/build_quarantine_recheck_evidence.py --write
```

This evidence builder prepares the quarantine/recheck gate; it does not quarantine files or mutate storage state.

## Current V0.1 lifecycle execution scaffold

The first compression/archive/restore execution slice is a non-mutating scaffold:

- importable code: `src/trading_storage/lifecycle_execution_scaffold.py`;
- executable wrapper: `scripts/lifecycle/build_lifecycle_execution_scaffold.py`;
- default input: a live dry-run lifecycle plan;
- optional input: an existing lifecycle-plan JSON;
- compression candidates produce compression manifest/receipt drafts and restore receipt drafts;
- archive candidates produce archive manifest/receipt drafts and restore receipt drafts;
- quarantine/delete candidates intentionally produce no deletion receipts;
- every draft carries `dry_run=true`, `mutation_performed=false`, and `status=planned_not_executed` where status applies.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/build_lifecycle_execution_scaffold.py
PYTHONPATH=src python3 scripts/lifecycle/build_lifecycle_execution_scaffold.py --write
```

This scaffold defines the receipt/manifest shape for future executors. It does not write compressed bytes, export SQL, run restore smoke tests, update the artifact index, delete files, or detach/drop SQL.

## Current V0.1 single-file compression executor

The first mutating lifecycle executor is deliberately constrained:

- importable code: `src/trading_storage/single_file_compression.py`;
- executable wrapper: `scripts/lifecycle/compress_single_file_candidates.py`;
- default mode is dry-run;
- `--apply` only writes zstd compressed copies for unprotected `compress_candidate` regular files;
- originals are always preserved;
- existing compressed outputs are refused unless `--overwrite` is passed;
- zstd decompression checksum smoke must pass before a successful receipt is emitted;
- artifact index updates, original deletion, quarantine moves, SQL archive/export, SQL detach/drop, model activation, broker execution, and account mutation remain disabled.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/compress_single_file_candidates.py
```

Reviewed apply shape:

```bash
PYTHONPATH=src python3 scripts/lifecycle/compress_single_file_candidates.py --lifecycle-plan-json <plan.json> --apply --write
```

This executor is allowed to write compressed copies under `storage/90_lifecycle/archive/compressed/`; it does not delete originals or mutate SQL/index state.

## Current V0.1 reviewed file-backed SQL archive executor

`src/trading_storage/sql_archive.py` and `scripts/lifecycle/execute_sql_archive.py` implement the first SQL-archive execution surface with a deliberately narrow boundary:

- default mode is dry-run;
- `--apply-reviewed-archive` writes gzip archive copies only for unprotected `archive_candidate` records;
- input is an already-materialized reviewed export file selected by the lifecycle plan;
- the executor verifies the source checksum before archive creation and verifies archive decompression checksum after creation;
- source files are preserved;
- there are no database connections, live SQL exports, SQL detach/drop actions, artifact-index mutations, quarantine moves, source deletions, model activation, broker execution, or account mutation.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/execute_sql_archive.py
PYTHONPATH=src python3 scripts/lifecycle/execute_sql_archive.py --lifecycle-plan-json <plan.json> --apply-reviewed-archive --write
```

## Current V0.1 archive restore verifier

`src/trading_storage/sql_archive.py` and `scripts/lifecycle/verify_sql_archive_restore.py` verify reviewed file-backed SQL archive copies by gzip decompression and checksum comparison. The verifier is `verification_only`; it does not materialize a database restore, attach SQL, detach/drop SQL, or mutate payloads.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/verify_sql_archive_restore.py --archive-result-json storage/90_lifecycle/execution/sql_archive_result.json
```

## Current V0.1 no-mutation quarantine/delete receipt builder

`src/trading_storage/quarantine_delete_executor.py` and `scripts/lifecycle/build_quarantine_delete_result.py` consume quarantine/recheck evidence and emit explicit quarantine/deletion/tombstone draft receipts. Gate-clear records are still `planned_not_executed`; physical quarantine moves and deletion remain disabled until a separate destructive executor is reviewed and approved.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/build_quarantine_delete_result.py --quarantine-recheck-json storage/90_lifecycle/quarantine_recheck/quarantine_recheck_evidence.json
```

## Current V0.1 one-pass file-lifecycle acceptance

`src/trading_storage/file_lifecycle_acceptance.py` and `scripts/lifecycle/run_file_lifecycle_acceptance.py` chain the reviewed file-lifecycle helpers into one safe pass:

1. build/write filesystem artifact index;
2. build/write protected set;
3. build/write dry-run lifecycle plan;
4. build/write quarantine/recheck evidence;
5. build/write compression/archive/restore execution scaffold;
6. optionally apply single-file compressed-copy creation for unprotected `compress_candidate` files;
7. build/write dashboard snapshot prune plan in dry-run mode unless an explicit later deletion approval is provided.

The acceptance emits `storage_file_lifecycle_acceptance` plus `storage_file_lifecycle_acceptance_summary`. It preserves originals and performs no artifact-index mutation, quarantine move, SQL archive/export, SQL detach/drop, model activation, broker execution, account mutation, or dashboard snapshot deletion by default. The current operational run uses `--apply-compression` only; dashboard/model-run deletion remains held until event-risk-governor regeneration and downstream review close.
