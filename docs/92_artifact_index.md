# Artifact Index and Dependency Graph

Status: accepted V0.1 design; physical SQL/file implementation deferred until dry-run lifecycle planning begins

## Purpose

The artifact index is the storage-owned inventory that lets lifecycle tools reason about artifacts by dependency and policy rather than by path alone.

A file scanner without an artifact index can report disk usage. It cannot safely decide whether a file is reusable source data, current promotion evidence, a model rollback artifact, or disposable scratch. The artifact index is therefore required before production cleanup execution.

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

- `keep_forever`: promoted model bodies, decisions, activation records, critical lineage;
- `compress_retain`: valuable source data or row-level history that should move to cold compressed storage;
- `archive_retain`: online detail that can be detached/exported but must remain restorable;
- `ttl_delete_after_quarantine`: regenerable scratch or cache that may be deleted after TTL and quarantine;
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
