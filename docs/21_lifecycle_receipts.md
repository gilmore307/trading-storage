# Lifecycle Receipts

Status: V0.1 compression receipt execution exists for single-file compressed-copy writes only; one-pass file-lifecycle acceptance summary exists; deletion, SQL archive, SQL detach/drop, and daemon receipts remain disabled

## Purpose

Lifecycle operations must leave durable evidence. If storage compresses, archives, restores, quarantines, or deletes something, future operators must know what happened, why, under which policy, and whether recovery is possible.

Receipt records are control evidence. They do not embed large payloads.

## Receipt families

### Current V0.1 receipt draft scaffold

The first receipt implementation slice is non-mutating and emits drafts only:

- `compression_manifest_draft_v1`;
- `compression_receipt_draft_v1`;
- `sql_archive_manifest_draft_v1`;
- `archive_receipt_draft_v1`;
- `restore_receipt_draft_v1`;
- wrapper contract `storage_lifecycle_execution_scaffold_v1`.

Draft receipts must use `status=planned_not_executed`, `dry_run=true`, and `mutation_performed=false`. They may record paths, checksums from the artifact index, planned archive/compression destinations, restore commands, and protected-set check status, but they must not claim successful compression/archive/restore/deletion.

### `compression_receipt`

Emitted after file/object compression completes and validation passes or fails. Current V0.1 execution support is limited to single-file zstd compressed-copy writes that preserve originals.

Required content:

- receipt id;
- policy id and rule id;
- artifact id(s);
- original path/URI;
- compressed path/URI;
- codec and read mode;
- original and compressed sizes;
- original and compressed checksums;
- protected-set check summary;
- restore-smoke result if required;
- executor version;
- timestamp;
- status;
- whether the original file was preserved;
- whether original deletion was performed;
- whether the artifact index was updated;
- whether SQL mutation was performed.

### Current V0.1 single-file compression receipts

The current executor emits:

- wrapper: `storage_single_file_compression_result_v1`;
- summary: `storage_single_file_compression_summary_v1`;
- manifest: `compression_manifest_v1`;
- receipt: `compression_receipt_v1`;
- restore check: `restore_receipt_v1`.

Allowed successful mutation is only writing `storage/archive/compressed/<artifact_id>/<original-name>.zst`. A successful receipt must still report `original_preserved=true`, `delete_original_performed=false`, `artifact_index_updated=false`, and `sql_mutation_performed=false`.

### Current V0.1 file-lifecycle acceptance receipts

The one-pass acceptance emits `storage_file_lifecycle_acceptance_v1` and `storage_file_lifecycle_acceptance_summary_v1` after chaining the current index/protected-set/plan/quarantine/scaffold/compression/dashboard-prune helpers. Its summary is an operator receipt for the pass, not a deletion receipt. It must explicitly report `delete_original_performed=false`, `artifact_index_updated=false`, `quarantine_move_performed=false`, `sql_mutation_performed=false`, `model_activation_performed=false`, `broker_execution_performed=false`, and `account_mutation_performed=false`.

### `archive_receipt`

Emitted after file or SQL archive creation. Current V0.1 implementation emits only `archive_receipt_draft_v1`; SQL archive execution does not exist yet.

Required content:

- receipt id;
- archive manifest ref;
- source artifact/table/partition refs;
- export command class;
- archive path/URI;
- checksum/digest;
- row count/schema/check summaries for SQL;
- protected-set check summary;
- restore-smoke result;
- detach/drop quarantine status if applicable;
- executor version;
- timestamp;
- status.

### `quarantine_recheck_evidence`

Emitted by the current report-only quarantine/recheck slice before any deletion executor exists.

Required content:

- evidence id or generated timestamp;
- source lifecycle-plan timestamp/ref;
- optional final protected-set timestamp/ref;
- artifact ids, paths, and URIs;
- lifecycle-plan action, policy id, and rule id;
- initial protected-set status and reason codes;
- quarantine candidate state;
- final recheck status and reason codes when supplied;
- explicit `deletion_allowed=false`;
- explicit `mutation_performed=false`.

This evidence is a gate input only. It is not a `deletion_receipt`, does not start a real quarantine waiting period, and does not authorize deletion.

### `deletion_receipt`

Emitted only after quarantine and final protected-set recheck pass.

Required content:

- receipt id;
- policy id and rule id;
- artifact id(s);
- deleted paths/URIs or table/partition refs;
- previous checksum and size;
- quarantine ref;
- initial and final protected-set check summaries;
- reason codes;
- tombstone ref;
- executor version;
- timestamp;
- status.

### `restore_receipt`

Emitted after restore verification or actual restore. Current V0.1 implementation emits only `restore_receipt_draft_v1` with `status=planned_not_executed` before restore execution exists.

Required content:

- receipt id;
- source archive/compression manifest ref;
- restored destination;
- restore mode: `verification_only` or `materialized_restore`;
- checksum/digest/schema/row-count checks;
- executor version;
- timestamp;
- status.

## Manifests

Lifecycle manifests describe restorable payloads:

- `compression_manifest` for compressed file/object artifacts;
- `sql_archive_manifest` for exported SQL table/partition archives;
- `restore_manifest` for how to restore a compressed/archive artifact.

Manifests should be referenced by receipts and artifact index rows.

## Tombstones

Deletion does not erase history. A deleted artifact leaves `artifact_tombstone` metadata:

| Field | Meaning |
| --- | --- |
| `artifact_id` | Deleted artifact id. |
| `deleted_at` | UTC deletion timestamp. |
| `deletion_receipt_ref` | Receipt proving protected-set/quarantine/deletion flow. |
| `previous_uri` | Previous logical URI. |
| `previous_path` | Previous physical path/table/export ref when applicable. |
| `previous_checksum_sha256` | Last known checksum. |
| `previous_size_bytes` | Last known size. |
| `policy_id` | Retention policy used. |
| `reason_codes` | Why deletion was allowed. |
| `restore_possible` | Whether any archive remains from which it can be restored. |
| `restore_manifest_ref` | Restore path when available. |

Tombstones let operators answer: did this artifact exist, why was it removed, who/what removed it, under which policy, and can it be restored?

## Storage rules

- Receipts and tombstones are never automatically deleted by the lifecycle daemon.
- Receipt payloads must not include secrets.
- Checksums must refer to canonical bytes/export bytes or reviewed table digests.
- A successful deletion receipt must never be emitted before final protected-set recheck.
- Failed lifecycle actions also emit receipts or failure records so retries are auditable.
