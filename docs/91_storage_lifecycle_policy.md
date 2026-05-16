# Storage Lifecycle Policy

Status: V0.1 dry-run planner, quarantine/recheck evidence, execution scaffold, and narrow single-file compression executor available; destructive mutation executors remain deferred

## Purpose

`trading-storage` owns lifecycle maintenance for durable trading artifacts, source data, model artifacts, SQL archives, local files, restore metadata, and deletion evidence.

The policy goal is not merely to free disk space. The goal is to make compression, archiving, restore, and deletion auditable lifecycle operations with dependency checks and receipts.

Core rule:

```text
Layer 1 and Layer 2 data are persistent source/feature foundations and must be retained, compressed, and protected from deletion by default.
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

### Later-layer model-run metadata

Includes Layer 3+ diagnostic summaries, runtime metadata, dashboard snapshots, staging/intermediate files, scratch feature files, failed-run temp files, duplicated dry-run payloads, and old stdout/stderr logs that are not the only remaining receipt/manifest/lineage evidence.

Policy: delete by TTL after the model run cycle closes and after latest summaries, receipts, manifests, lineage refs, and unresolved-alert evidence are preserved. Keep only compact summary/receipt evidence after the retention window.

### Downloaded source data

Source data is classified by reproducibility and reuse:

- point-in-time, vintage, revision-sensitive, provider-window-limited, expensive, paid-window, option history, SEC filing snapshots, GDELT historical pulls, and lineage-referenced source data: compress and retain by default;
- stable re-downloadable provider cache and one-off experiment pulls without lineage references: TTL delete may be allowed after quarantine;
- shared normalized source data: retain or compress while any active/promoted/review lineage may reference it.

Policy: source data is compressed before deletion unless the policy explicitly classifies it as disposable cache.

### SQL data

Online summary and current control-plane facts remain online. Closed row-level detail, old feature partitions, historical source partitions, and old evaluation details may be exported and compressed. SQL temporary/intermediate tables may be deleted by TTL when reproducible.

Policy: never compress PostgreSQL live data files directly. Archive through dump/export and restore smoke.

## Retention defaults

- Layer 1 market-regime data: persistent; compress/archive if needed, do not auto-delete;
- Layer 2 sector-context data: persistent; compress/archive if needed, do not auto-delete;
- promoted model bodies: permanent;
- promotion/review/activation/deactivation receipts: permanent;
- dataset snapshot/split manifests: permanent or lineage lifetime;
- PIT/vintage/source history: compress and retain by default;
- dashboard/read-model latest summaries: retained;
- dashboard/read-model high-frequency snapshots: metadata TTL after model-run cycle close; current default prune plan keeps the latest 24 snapshots per contract and marks snapshots older than 24 hours as delete candidates, but apply is currently on hold until the event-model redo and downstream model regeneration are complete/reviewed;
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

## Current V0.1 dry-run planner

The first durable-artifact lifecycle planner is conservative and non-mutating:

- importable code: `src/trading_storage/lifecycle_planner.py`;
- executable wrapper: `scripts/lifecycle/plan_storage_lifecycle.py`;
- default input: a live bounded artifact-index scan plus a freshly built protected set;
- optional inputs: existing artifact-index JSONL, existing protected-set JSON, and reviewed JSON policy rules;
- default output behavior prints a summary only; `--write` writes `storage/lifecycle_plan/storage_lifecycle_plan.json` and `storage/lifecycle_plan/storage_lifecycle_plan_summary.json`;
- all output records carry `dry_run=true` and `mutation_performed=false` in the summary;
- protected artifacts become `retain_protected` regardless of matched lifecycle policy;
- ambiguous manual-review artifacts remain retained until metadata is classified.

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
- default output behavior prints a summary only; `--write` writes `storage/quarantine_recheck/quarantine_recheck_evidence.json` and `storage/quarantine_recheck/quarantine_recheck_summary.json`;
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

This is the only current lifecycle executor allowed to write bytes, and those bytes are compressed copies under `storage/archive/compressed/`.
