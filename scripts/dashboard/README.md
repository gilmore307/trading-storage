# Dashboard Scripts

Executable helpers for storage-hosted dashboard summary/read-model payloads.

- `materialize_read_model.py` validates one dashboard read-model JSON envelope and writes the accepted storage layout: snapshot, `latest.json`, schema, and index row.

These helpers do not create dashboard UI, refresh jobs, provider calls, model activation, broker execution, or account mutation.
