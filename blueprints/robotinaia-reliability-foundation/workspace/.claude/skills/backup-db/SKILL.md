---
name: backup-db
description: Back up robotinaia.db before any schema-changing step and know how to restore it. Use before every DB-schema-touching step in the reliability-foundation blueprint (steps 05, 06, 07, 10, 13, 14).
---

# Back up robotinaia.db before a schema change

Every DB-schema-touching step in `blueprints/robotinaia-reliability-foundation/blueprint.md` §9 starts
with a real, executable backup of the live SQLite file — this captures that pattern once so it is not
reinvented per step.

## When to use

Before any command that runs `ALTER TABLE`, `apply_migrations()`, or any script under `migrations/`.
Concretely, steps 05, 06, 07, 10, 13, 14 of the reliability-foundation blueprint.

## Steps

1. Back up with the step's number in the filename, so multiple backups never collide:
   ```bash
   cp robotinaia.db robotinaia.db.backup-step-NN
   ```
   If no live DB exists yet (fresh environment), this is a no-op — confirm with:
   ```bash
   cp robotinaia.db robotinaia.db.backup-step-NN 2>/dev/null || echo "no live DB yet, nothing to back up"
   ```
2. Run the schema-changing step.
3. Verify the result (row counts, `PRAGMA foreign_key_check`, etc. — see the step's own `Verify`
   block).
4. If anything looks wrong, restore immediately:
   ```bash
   cp robotinaia.db.backup-step-NN robotinaia.db
   ```

## Verify

The backup file exists on disk (`ls robotinaia.db.backup-step-NN`) before the schema-changing command
runs.

## Do not

- Do not skip the backup because "I'm only testing against a copy" — the backup is the *production*
  rollback target, independent of whatever copy a `Verify` command also happens to use.
- Do not overwrite an existing backup file for a different step number.
