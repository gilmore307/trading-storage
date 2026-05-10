# Compression, Archive, and Restore

Status: accepted V0.1 design; execution must remain dry-run until protected-set and receipt support exist

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
  -> write compression_manifest_v1
  -> write compression_receipt_v1
  -> update artifact index
  -> remove uncompressed copy only if policy allows
```

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
  -> write sql_archive_manifest_v1
  -> write archive_receipt_v1
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
- emit `restore_receipt_v1`;
- leave production state untouched unless explicitly requested.

## Initial implementation order

1. Docs + policy + registry names.
2. Artifact index + protected-set builder.
3. Dry-run lifecycle scanner/planner.
4. File compression executor.
5. SQL archive executor.
6. Restore verifier.
7. Lifecycle daemon / scheduled maintenance.

The daemon must remain dry-run by default until execution policies have been reviewed on the target host.
