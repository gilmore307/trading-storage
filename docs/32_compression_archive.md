# Compression and Archive

Status: V0.1 single-file compression executor and one-pass safe file-lifecycle acceptance available; deletion, SQL archive, SQL detach/drop, and daemon execution remain disabled until reviewed executors are approved

## Purpose

Compression and archive reduce disk pressure without destroying audit, rollback, and rebuild paths. The lifecycle system distinguishes compressed artifacts that remain directly readable from archives that require restore.

## Compression tiers

### Hot

Current active task/review/model dependencies. No compression, movement, SQL detach/drop, or deletion.

### Warm

Likely to be read soon. May be converted to direct-readable compressed formats when consumers support them, e.g. parquet with zstd compression.

### Cold compressed

No active direct readers/writers; useful for audit, reuse, or rebuild. Compress and verify; remove uncompressed copy only when policy allows.

### Archive

Low-frequency access. Restore is required before detailed use. Must have manifest, checksum, restore command, and restore-smoke evidence.

## File compression

Recommended formats:

| Payload | Preferred form |
| --- | --- |
| text/json/jsonl/csv | zstd or tar+zstd for directories |
| parquet | native zstd compression |
| logs | zstd |
| raw provider responses | zstd unless classified as disposable cache |
| directory bundles | tar.zst |

File compression flow:

```text
identify candidate
  -> protected-set/active-writer check
  -> compress
  -> checksum original
  -> checksum compressed result
  -> restore smoke if read_mode=restore_required
  -> write compression_manifest
  -> write compression_receipt
  -> update artifact index
  -> remove uncompressed copy only if policy allows
```

## Current V0.1 execution scaffold

The first compression/archive/restore implementation slice is a non-mutating scaffold:

- importable code: `src/trading_storage/lifecycle_execution_scaffold.py`;
- executable wrapper: `scripts/lifecycle/build_lifecycle_execution_scaffold.py`;
- default input: a live dry-run lifecycle plan;
- optional input: existing lifecycle-plan JSON via `--lifecycle-plan-json`;
- output contracts: `compression_manifest_draft`, `compression_receipt_draft`, `sql_archive_manifest_draft`, `archive_receipt_draft`, and `restore_receipt_draft` inside `storage_lifecycle_execution_scaffold`;
- default output behavior prints a summary only; `--write` writes `storage/90_lifecycle/execution/lifecycle_execution_scaffold.json` and `storage/90_lifecycle/execution/lifecycle_execution_scaffold_summary.json`;
- protected lifecycle-plan rows are skipped;
- `compress_candidate` rows produce compression manifest/receipt drafts plus a restore verification receipt draft;
- `archive_candidate` rows produce archive manifest/receipt drafts plus a restore verification receipt draft;
- `quarantine_candidate` rows do not produce deletion receipts; deletion remains gated by quarantine/recheck and a future reviewed delete executor.

Every draft has `dry_run=true` and `mutation_performed=false`; status is `planned_not_executed`. No compressed bytes, SQL exports, restore materializations, artifact-index mutations, SQL detach/drop, or deletion are performed.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/build_lifecycle_execution_scaffold.py
PYTHONPATH=src python3 scripts/lifecycle/build_lifecycle_execution_scaffold.py --write
```

## Current V0.1 single-file compression executor

The first reviewed mutating slice is deliberately narrow:

- importable code: `src/trading_storage/single_file_compression.py`;
- executable wrapper: `scripts/lifecycle/compress_single_file_candidates.py`;
- default mode is dry-run and writes no compressed bytes;
- `--apply` is required before any compressed copy is written;
- only unprotected `compress_candidate` rows are eligible;
- eligible source must be a regular file under the selected repository/root, not a symlink or directory;
- output path is `storage/90_lifecycle/archive/compressed/<artifact_id>/<original-name>.zst`;
- existing compressed outputs are refused unless `--overwrite` is passed;
- original files are always preserved;
- artifact index is not mutated;
- deletion/quarantine/SQL detach/drop are not performed;
- zstd decompression checksum smoke verifies that decompressed bytes match the original checksum before a successful receipt is emitted.

The executor emits `storage_single_file_compression_result` with `compression_manifest`, `compression_receipt`, and `restore_receipt`. In apply mode, `mutation_performed=true` means only that a compressed copy was written; `delete_original_performed=false`, `artifact_index_updated=false`, and `sql_mutation_performed=false` remain explicit.

CLI smoke:

```bash
PYTHONPATH=src python3 scripts/lifecycle/compress_single_file_candidates.py
# Apply only after reviewing the lifecycle plan and candidates:
PYTHONPATH=src python3 scripts/lifecycle/compress_single_file_candidates.py --lifecycle-plan-json <plan.json> --apply --write
```

## Compression manifest shape

Compression manifest fields:

- original path/URI;
- compressed path/URI;
- codec;
- read mode;
- original size and compressed size;
- checksums;
- artifact id and artifact kind;
- lineage refs;
- policy id and rule id;
- restore command if needed;
- compression timestamp;
- executor version.

## SQL archive

SQL compression is archive/export based. Do not compress PostgreSQL live data directory files.

Recommended SQL archive approaches:

- `pg_dump -Fc` for table/partition schema + data archive;
- CSV/Parquet export + zstd for analytical row partitions;
- monthly/quarterly partition archive by source/feature/model-output family;
- online summary retained while row-level detail is archived.

SQL archive flow:

```text
closed partition/table
  -> verify no active online dependency
  -> export schema
  -> export data
  -> compress dump/export
  -> checksum
  -> restore smoke in isolated destination
  -> write sql_archive_manifest
  -> write archive_receipt
  -> update artifact index
  -> detach/drop online partition only if policy allows after quarantine
```

## Summarize then archive detail

For large SQL/detail families, storage should keep compact online summary while archiving row-level detail.

Online summary should include, where applicable:

- row count;
- byte count;
- min/max timestamps;
- symbol/target/sector coverage;
- feature/label/evaluation coverage;
- source provider and window;
- checksum or digest;
- archive artifact ref;
- restore command/ref.

This lets manager/dashboard answer whether evidence exists without restoring the full detail archive.

## Restore verifier

Restore verification is a first-class phase. Compression/archive cannot be trusted until restore has been tested.

Restore verifier responsibilities:

- read manifest;
- restore into an isolated temp directory/database/schema;
- verify checksum/digest/row count/schema;
- emit `restore_receipt`;
- leave production state untouched unless explicitly requested.

## Initial implementation order

1. Docs + policy + registry names.
2. Artifact index + protected-set builder.
3. Dry-run lifecycle scanner/planner.
4. Dry-run quarantine/recheck evidence builder.
5. Non-mutating compression/archive/restore manifest and receipt scaffold.
6. Reviewed single-file compression executor that preserves originals.
7. One-pass safe file-lifecycle acceptance that runs current evidence builders and optional compressed-copy creation together.
8. Reviewed SQL archive executor.
9. Restore verifier.
10. Lifecycle daemon / scheduled maintenance.

The daemon must remain dry-run by default until execution policies have been reviewed on the target host.
