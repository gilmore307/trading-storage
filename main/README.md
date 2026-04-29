# Main Shared Assets

`main/` stores checked-in reusable non-code assets shared across trading repositories.

This directory was migrated from `trading-main/storage/` so `trading-main` can keep global registry/guidance responsibilities while `trading-storage` owns storage and shared asset placement.

## Contents

- `templates/` — trading-wide reusable drafting and implementation templates.
- `shared/` — trading-wide static/shared files that are not templates and are safe for other repositories to reference.

Runtime outputs, generated artifacts, secrets, caches, and local environment files do not belong here.
