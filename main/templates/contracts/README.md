# Contract Templates

This directory stores reusable templates for system-level trading contracts.

Templates belong here instead of `docs/` because they are drafting surfaces, not ratified system docs.

Current templates:

- `artifact.md` — artifact contract drafting template.
- `manifest.md` — manifest contract drafting template.
- `ready_signal.md` — ready-signal contract drafting template.
- `request.md` — request contract drafting template.

When a contract becomes concrete, its stable type names should be registered in `scripts/` and its concrete entries should be inserted through SQL registry migrations.

See `../../../../docs/92_templates.md` for template acceptance and promotion rules.
