# Protected Set Policy

Status: V0.1 conservative filesystem implementation available; production mutation still requires quarantine/recheck/receipts before deletion or SQL detach/drop

## Purpose

The protected set is the storage-owned safety boundary for lifecycle work. Before compression, archive, SQL detach/drop, quarantine, or deletion, storage must determine which artifacts and SQL partitions are currently protected by model lineage, active tasks, review evidence, downstream chains, or control-plane records.

A cleanup tool that cannot build a protected set may produce a report, but it must not delete or detach durable artifacts.

## Current V0.1 implementation

The first implementation slice is conservative and filesystem/artifact-index based:

- importable code: `src/trading_storage/protected_set.py`;
- executable wrapper: `scripts/lifecycle/build_protected_set.py`;
- default input: a live bounded artifact-index scan using `storage/artifacts/`;
- optional input: existing artifact-index JSONL via `--index-jsonl`;
- optional protected-reference input: JSON object keyed by protected reason code via `--reference-file`;
- optional manual pins: repeated `--manual-pin <artifact-id-or-ref>`;
- optional mutation candidates: repeated `--candidate <artifact-id-or-ref>`;
- default output behavior prints the summary only; `--write` writes `storage/protected_set/protected_set.json` and `storage/protected_set/protected_set_summary.json`;
- all artifacts with `unknown_metadata` remain protected, which is the default for ambiguous artifact-index rows.

This builder only produces safety evidence. It does not compress, archive, delete, quarantine, detach SQL, or authorize production mutation by itself.

## Protected inputs

The builder must inspect or receive references from:

- promoted model lineage;
- current active model lineage;
- active review/promotion candidates;
- activation/deactivation records;
- manager `manager_request` records for open work;
- manager `run_manifest`, `artifact_ref`, and `ready_signal` rows;
- dataset snapshot/split manifests;
- current downstream target chain state;
- open task/run manifests;
- SQL online dependency metadata;
- lifecycle quarantine records;
- manually pinned artifacts.

## Protected reason codes

Initial reason codes:

| Code | Meaning |
| --- | --- |
| `current_promoted_model_lineage` | Artifact is required by the current promoted model. |
| `old_promoted_model_body` | Artifact is part of an old promoted model body and must be retained. |
| `active_review_lineage` | Artifact is referenced by an active review/promotion candidate. |
| `active_run_input_or_output` | Artifact belongs to an open run/task. |
| `ready_signal_consumable` | A ready signal marks the artifact consumable by downstream workflows. |
| `dataset_snapshot_or_split` | Artifact is a frozen dataset snapshot/split manifest or required evidence. |
| `active_target_chain_dependency` | Current target-major chain may still consume it. |
| `source_data_shared_dependency` | Source data may be reused by another model or feature family. |
| `sql_online_dependency` | SQL partition/table is still queried online. |
| `manual_pin` | Human/operator/reviewer pinned it. |
| `unknown_metadata` | Metadata is insufficient; protect until classified. |

## Lifecycle gate rules

- Deletion requires protected set clear, quarantine, and a final protected-set recheck.
- SQL detach/drop requires protected set clear, archive/restore verification, quarantine, and a final protected-set recheck.
- Compression requires no active writer and no active consumer that requires the uncompressed path.
- Direct-readable compression may preserve consumability if the artifact URI/read mode is updated through reviewed metadata.
- Restore-required archives must not replace online artifacts while consumers still need direct reads.

## Quarantine-before-delete

Deletion flow:

```text
delete_candidate
  -> protected-set check
  -> quarantined_for_delete for 7-30 days
  -> final protected-set recheck
  -> deletion_receipt
  -> artifact_tombstone
  -> deleted
```

The quarantine record should include artifact ids, paths/URIs, policy id, reason codes, first check timestamp, quarantine expiry, and review/approval refs if any.

If any protected reason appears during the final recheck, deletion is cancelled and the artifact returns to the appropriate protected lifecycle state.

## Compression safety

Compression flow:

```text
cold_compressible
  -> verify no active writer
  -> verify no direct-read consumer requires current path
  -> compress
  -> checksum original and compressed payload/export
  -> restore smoke when restore_required
  -> compression_receipt
  -> cold_compressed
```

Deleting the uncompressed copy after compression is a separate policy decision unless the compression rule explicitly permits `delete_uncompressed_after_verify=true`.

## SQL archive safety

SQL archive flow:

```text
closed partition/table
  -> protected-set check
  -> export schema and data
  -> compress archive
  -> checksum
  -> restore smoke
  -> archive_receipt
  -> optional quarantine for online detach/drop
  -> detach/drop online copy only after final recheck
```

Live PostgreSQL data files must never be compressed directly.

## CLI smoke

```bash
PYTHONPATH=src python3 scripts/lifecycle/build_protected_set.py
PYTHONPATH=src python3 scripts/lifecycle/build_protected_set.py --candidate <artifact-id-or-path>
PYTHONPATH=src python3 scripts/lifecycle/build_protected_set.py --write
```

A candidate with any protected reason is blocked. A candidate with no protected reasons may be reported clear, but deletion/SQL detach-drop still requires the later quarantine/recheck/receipt implementation slices.
