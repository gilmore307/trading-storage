# Storage Lifecycle Policy

Status: accepted V0.1 design; implementation starts as dry-run planning only

## Purpose

`trading-storage` owns lifecycle maintenance for durable trading artifacts, source data, model artifacts, SQL archives, local files, restore metadata, and deletion evidence.

The policy goal is not merely to free disk space. The goal is to make compression, archiving, restore, and deletion auditable lifecycle operations with dependency checks and receipts.

Core rule:

```text
Promoted model bodies are preserved permanently.
Regenerable intermediate training data may be deleted after TTL.
Downloaded source data is compressed before deletion and deleted only when safely reproducible and unreferenced.
SQL detail is partition/table archived through export + compression; live database files are never compressed directly.
Every compression, archive, delete, and restore action writes manifest/receipt evidence.
```

## Repository responsibilities

### trading-manager

Owns the unified control-plane view for lifecycle maintenance: lifecycle requests, priorities, deadlines, task summary visibility, scheduling intent, run/artifact/ready refs, workflow state, promotion/review decisions, and lifecycle request routing. Storage lifecycle work should enter normal operation through `manager_request_v1`/`storage_lifecycle_request_v1` so it is visible beside data/model tasks.

Manager may request, prioritize, schedule, and observe storage lifecycle work, but it does not delete files, compress SQL, mutate storage paths, choose physical storage actions by itself, or bypass storage protected-set checks.

### trading-data

Owns source acquisition, normalization, and feature/source artifact semantics. Completion receipts should describe artifact kind, reproducibility class, source provider, source times, lineage refs, rebuild hints, and recommended retention class so storage can classify outputs safely.

### trading-model

Owns model artifacts, evaluation artifacts, promotion candidates, model versions, and model lineage. Model/evaluation/promotion artifacts should identify model id/version, dataset snapshot/split refs, feature contract refs, source refs, code version refs, and promotion/activation refs where available.

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

### Regenerable intermediate training data

Includes temporary train matrices, scratch feature files, staging parquet/csv/jsonl, failed-run temp files, duplicated dry-run payloads, old stdout/stderr logs, and unpromoted candidate intermediates.

Policy: delete by TTL when reproducible from source data, manifests, and code version. Keep only summary/receipt evidence after the retention window.

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

- promoted model bodies: permanent;
- promotion/review/activation/deactivation receipts: permanent;
- dataset snapshot/split manifests: permanent or lineage lifetime;
- PIT/vintage/source history: compress and retain by default;
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
policy_id: storage_lifecycle_default_v1
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
