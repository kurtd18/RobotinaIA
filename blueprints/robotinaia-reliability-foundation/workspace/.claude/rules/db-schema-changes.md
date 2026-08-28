# Rule: Database schema changes

Applies to any change touching `app/database/schema.py`, `app/database/connection.py`,
`app/database/migrations.py`, or any `migrations/*.py` script, in this repo, at any time — not just
during the reliability-foundation blueprint's build.

1. **Back up `robotinaia.db` first, always**: `cp robotinaia.db robotinaia.db.backup-<label>`. See
   `.claude/skills/backup-db/SKILL.md`.
2. **Every table definition lives in `app/database/schema.py`.** Never declare a `CREATE TABLE` in a
   repository module (`app/scheduler/repository.py`, `app/paper_trading/repository.py`, etc.) — those
   modules may keep a thin `crear_tabla()` call-through for backward compatibility, but the
   authoritative SQL text lives in one place.
3. **SQLite cannot `ALTER TABLE ADD CONSTRAINT` a `CHECK`.** Use the rebuild pattern: create
   `<table>_new` with the full target schema, `INSERT INTO ... SELECT`, drop the old table, rename.
   `app/database/migrations.py` owns this pattern.
4. **`PRAGMA foreign_keys` does not persist across connections** — it must be reissued in
   `get_connection()` on every call, not once at startup.
5. **Any migration touching existing rows asserts row-count parity before/after and exits non-zero on
   mismatch.** Never silently drop or ignore a row that fails to migrate cleanly.
6. **After any schema change**, run:
   ```bash
   sqlite3 robotinaia.db "PRAGMA foreign_key_check;"   # expect: no rows
   pytest tests/ -q                                     # expect: exit 0
   ```
