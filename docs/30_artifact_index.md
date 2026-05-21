# Artifact Index and Dependency Graph

Status: V0.1 filesystem JSONL implementation available; SQL-backed dependency graph remains deferred until dry-run lifecycle planning requires it

## Purpose

The artifact index is the storage-owned inventory that lets lifecycle tools reason about artifacts by dependency and policy rather than by path alone.

A file scanner without an artifact index can report disk usage. It cannot safely decide whether a file is reusable source data, current promotion evidence, a model rollback artifact, or disposable scratch. The artifact index is therefore required before production cleanup execution.

## Current V0.1 implementation

The first implementation slice is conservative and filesystem-only:

- importable code: `src/trading_storage/artifact_index.py`;
- executable wrapper: `scripts/lifecycle/build_artifact_index.py`;
- default scanned roots: `storage/01_source_data/`, `storage/02_control_plane/`, `storage/03_model_artifacts/`, `storage/04_execution_artifacts/`, `storage/05_replay_datasets/`, and `storage/06_dashboard_cache/read_models/`; specific files or bounded roots can be added with repeated `--include-root` arguments;
- default optional outputs: `storage/90_lifecycle/artifact_index/artifact_index.jsonl` and `storage/90_lifecycle/artifact_index/artifact_index_summary.json`;
- default CLI behavior prints the summary only; `--write` is required to write index files;
- indexed payloads are never mutated;
- ambiguous artifacts default to `reproducibility_class=unknown`, `retention_class=manual_review_required`, and `protected_reason_codes=[unknown_metadata]`;
- payload metadata may explicitly set `storage_retention_class`/`retention_class` and `storage_reproducibility_class`/`reproducibility_class` when a producer has a reviewed lifecycle classification;
- explicit Layer 1/2 data hints classify as `retention_class=compress_and_retain` with no deletion-protection reason so compression planning can proceed while deletion remains out of policy;
- Layer 1/2 runtime, log, scratch, staging, cache, and intermediate path hints classify as `ttl_delete_allowed`; this exception covers disposable run material only, not reusable source/feature foundations;
- replay model-pipeline result summaries classify as `keep_forever` and are protected by `replay_result_summary`;
- non-replay artifacts explicitly classified as `keep_forever` are protected by `keep_forever_retention`;
- replay reusable Layer 1/2 and event/news inputs classify as `compress_and_retain`;
- replay model-specific option snapshot/download hints classify as `ttl_delete_allowed` after replay close when summaries, manifests, and receipts are retained;
- `fold_complete_delete_allowed` is reserved for explicitly fold-scoped target/source artifacts that may become quarantine candidates only after full-fold completion; reusable Layer 1/2 source foundations must not use this class;
- dashboard `latest.json` read models classify as `dashboard_latest_retained` and protected;
- explicitly indexed dashboard snapshots classify as `ttl_delete_allowed` because they are metadata caches, not canonical Layer 1/2 data; the dashboard snapshot pruner separately keeps the latest 10 snapshots per contract by default.

This is enough for dry-run inventory and protected-set preparation. It is not a production deletion authorization surface. Do not point a routine scan at an unbounded snapshot-heavy read-model tree unless the caller deliberately wants that full inventory cost; use the bounded dashboard snapshot lifecycle helper for snapshot metadata pruning.

## Minimal artifact index fields

| Field | Meaning |
| --- | --- |
| `artifact_id` | Stable artifact id. Content changes require a new artifact id. |
| `artifact_kind` | Registered or reviewed kind such as `promoted_model_artifact`, `pit_source_data`, `feature_matrix`, `sql_partition_archive`. |
| `producer_repo` | Producing repository. |
| `producer_component` | Source/model/script/workflow that produced the artifact. |
| `producer_run_id` | Producing run id or manifest id. |
| `artifact_uri` | Durable logical URI used by consumers. |
| `physical_path` | Current physical file path/table/export path when applicable. |
| `storage_backend` | `postgres`, `filesystem`, `object_store`, `registry_snapshot`, or reviewed equivalent. |
| `created_at` | UTC artifact creation time. |
| `available_time` | Earliest point-in-time at which the payload may be used. |
| `artifact_size_bytes` | Size of the current payload or archive. |
| `checksum_sha256` | Hash of canonical bytes, export bytes, or reviewed table digest. |
| `content_codec` | `none`, `zstd`, `parquet_zstd`, `pg_dump_custom`, `tar_zstd`, etc. |
| `content_format` | `json`, `jsonl`, `csv`, `parquet`, `postgres_table`, `pg_dump`, etc. |
| `read_mode` | `direct_readable`, `restore_required`, or `metadata_only`. |
| `schema_ref` | Contract/schema reference for interpreting the payload. |
| `manifest_ref` | Producing `run_manifest` or lifecycle manifest. |
| `lineage_refs` | Upstream artifact/model/source refs used to create this artifact. |
| `dependency_refs` | Artifacts that must remain available while this artifact is protected. |
| `reproducibility_class` | How safely the artifact can be recreated. |
| `retention_class` | Retention intent selected by policy. |
| `lifecycle_state` | Current lifecycle state. |
| `protected_reason_codes` | Current reasons preventing deletion or mutation. |
| `last_lifecycle_scan_at` | Last scan timestamp. |
| `last_lifecycle_action_at` | Last compression/archive/delete/restore action timestamp. |

## Reproducibility classes

Use these values until a later registry expansion changes them:

| Value | Meaning |
| --- | --- |
| `non_reproducible` | Cannot be recreated if deleted. |
| `provider_window_limited` | Provider/source access changes over time or has paid/history windows. |
| `expensive_to_reproduce` | Rebuild is possible but costly in provider calls, compute, or time. |
| `reproducible_with_manifest` | Rebuild is possible when source refs, code version, config, and manifest exist. |
| `fully_reproducible` | Safe cache/scratch that can be regenerated from durable upstream artifacts. |
| `unknown` | Default until classified; must be treated conservatively. |

Deletion policy must depend strongly on `reproducibility_class`. `unknown`, `non_reproducible`, `provider_window_limited`, and `expensive_to_reproduce` cannot enter direct deletion without reviewed exception.

## Retention classes

Initial retention classes:

- `keep_forever`: promoted model bodies, decisions, activation records, critical lineage, and model-pipeline replay result summaries;
- `compress_and_retain`: valuable source data or row-level history that should move to cold compressed storage while remaining retained, including Layer 1/2 data foundations;
- `archive_retain`: online detail that can be detached/exported but must remain restorable;
- `ttl_delete_allowed`: regenerable scratch, cache, dashboard snapshots outside the recent-count hot window, Layer 1/2 runtime/log/intermediate files, and later-layer model-run metadata that may be deleted after TTL/quarantine/run-cycle closure;
- `fold_complete_delete_allowed`: target-symbol or experiment-specific source artifacts scoped to one completed model-worker fold and managed as a fold folder, not reusable Layer 1/2 foundations;
- `dashboard_latest_retained`: current dashboard `latest.json` summaries that should remain hot and protected;
- `metadata_only_after_archive`: detail can leave online storage after summary/manifest/archive is verified;
- `manual_review_required`: default for ambiguous or high-risk artifacts.

## Read modes

`read_mode` distinguishes compressed payloads that remain directly consumable from archives that require restoration:

- `direct_readable`: consumers can read the artifact in place, e.g. `parquet` with zstd compression;
- `restore_required`: consumers must run a restore step first, e.g. `tar.zst` bundle or `pg_dump -Fc`;
- `metadata_only`: only summary/tombstone/manifest remains online.

Downstream consumers must not assume a compressed artifact is directly readable unless `read_mode=direct_readable`.

## Dependency graph

The dependency graph is derived from:

- artifact index `lineage_refs` and `dependency_refs`;
- manager `artifact_ref` and `ready_signal` rows;
- run manifests;
- dataset snapshot/split manifests;
- model promotion and activation records;
- active target chains;
- SQL partition/archive manifests.

The dependency graph decides what is protected, what can be compressed, what can be archived, and what can enter delete quarantine.

## Producer metadata requirements

`trading-data` completion receipts should include artifact kind, source provider, source available/as-of times, lineage refs, rebuild hints, reproducibility class, and recommended retention class.

`trading-model` artifacts should include model id, model version, dataset snapshot/split refs, feature contract refs, source refs, code version refs, promotion decision refs, and activation refs where relevant.

Without sufficient metadata, lifecycle tooling must classify the artifact as `unknown` and `manual_review_required`.

## CLI smoke

```bash
PYTHONPATH=src python3 scripts/lifecycle/build_artifact_index.py
PYTHONPATH=src python3 scripts/lifecycle/build_artifact_index.py --write
```

The first command prints only a summary. The second writes the JSONL index and summary under ignored local storage.
