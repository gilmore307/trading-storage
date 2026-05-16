# Lifecycle Receipts and Tombstones

Status: accepted V0.1 design; quarantine/recheck evidence is implemented, while mutation receipt schemas remain minimal until executors are reviewed

## Purpose

Lifecycle operations must leave durable evidence. If storage compresses, archives, restores, quarantines, or deletes something, future operators must know what happened, why, under which policy, and whether recovery is possible.

Receipt records are control evidence. They do not embed large payloads.

## Receipt families

### `compression_receipt`

Emitted after file/object compression completes and validation passes or fails.

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
- status.

### `archive_receipt`

Emitted after file or SQL archive creation.

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

Emitted after restore verification or actual restore.

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
