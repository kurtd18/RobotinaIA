# Epic 02: Database Integrity & Concurrency

> After this epic, the production-risk `UMBRAL_SENAL` bug is fixed, tests run against an isolated
> temp DB, SQLite runs WAL with a busy timeout, every table is defined once in `schema.py` with real
> FK/CHECK constraints, and schema changes are tracked via `PRAGMA user_version`.

| | |
|---|---|
| **Epic id** | `02-database-integrity-and-concurrency` |
| **Tasks** | `E2-T1` … `E2-T5` |
| **Depends on** | nothing for `E2-T1`/`E2-T2`; `E2-T3` needs `E2-T2`; `E2-T4` needs `E2-T3`; `E2-T5` needs `E2-T4` |
| **Unlocks** | `04-unified-portfolio-and-pnl`, `06-scheduler-resilience`, `07-telegram-dashboard-consolidation` (E7-T3) |
| **Parallel with** | `01-security-blockers`, `03-unified-market-data-provider` |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · SQLite via raw `sqlite3` (no ORM) · `pytest` · `loguru`.

| Task | Command |
|---|---|
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |
| Init/verify DB | `python init_db.py` |
| Inspect schema | `sqlite3 robotinaia.db "PRAGMA table_info(<table>);"` |
| Backup before schema change | `cp robotinaia.db robotinaia.db.backup-step-NN` |

**Gate:** `pytest tests/ -q` passes before any task here is marked done.

`E2-T3` onward touches the live `robotinaia.db` — **always back it up first** (each task's Verify
includes the backup command; do not skip it even when testing against a copy).

## Directory subtree

```
app/
  core/
    settings.py                 # EDIT (E2-T1) — adds UMBRAL_SENAL
  database/
    connection.py                # EDIT (E2-T3) — WAL, busy_timeout, foreign_keys pragma
    schema.py                    # EDIT (E2-T4) — consolidated tables, FK/CHECK, user_version hook
    migrations.py                # NEW (E2-T4) — versioned migration runner
  scheduler/
    repository.py                # EDIT (E2-T4) — scheduler_runs moves into schema.py
  paper_trading/
    repository.py                # EDIT (E2-T4) — paper_positions moves into schema.py
tests/
  conftest.py                    # NEW (E2-T2) — db_path fixture
  test_alert.py                  # exists, unedited — passes once E2-T1 lands
  test_connection.py             # NEW (E2-T3)
  test_schema_constraints.py     # NEW (E2-T4)
migrations/
  0000_apply_constraints.py      # NEW (E2-T5)
tests/
  test_migration_row_counts.py   # NEW (E2-T5)
```

## Data model touched here

| Entity | Fields this epic adds or reads | Notes |
|---|---|---|
| `portfolio_decisions` | `position_id` gets `REFERENCES portfolio(id)` | previously no FK |
| `signals` | `signal` gets `CHECK (signal IN ('PENDING','EXECUTED','SOLD','EXPIRED'))` | previously free text |
| `portfolio` | `status` gets `CHECK (status IN ('OPEN','CLOSED'))` | previously free text; `asset_class`/`normalized_symbol` columns are added later, in Epic 4 — do not add them here |
| `scheduler_runs`, `paper_positions` | definitions consolidated into `schema.py` | data unchanged, only *where the CREATE TABLE lives* changes |
| `stock_scheduler_runs`, `alert_state` | new tables, defined here | not used until Epics 5/6; defining now avoids a second schema-touching step later |

## Contracts

**Consumed** — nothing; this epic is foundational.

**Produced**:

| Export | Signature | Used by |
|---|---|---|
| `app/database/connection.get_connection()` | returns a `sqlite3.Connection` with WAL, busy_timeout, foreign_keys already set | every module in every later epic |
| `app/database/migrations.apply_migrations(conn)` | idempotent, bumps `PRAGMA user_version` | `04-unified-portfolio-and-pnl` (E4-T1, adds its own migration entry) |
| `app/core/settings.Settings.UMBRAL_SENAL` | `int = 80` | `app/services/alert_engine.py` (already reads it, was broken) |

## Conventions that bite in this area

- **SQLite does not persist `PRAGMA foreign_keys` across connections** — it must be reissued on every
  `sqlite3.connect()` call inside `get_connection()`, not once at startup.
- SQLite's `ALTER TABLE` cannot add a `CHECK` constraint to an existing column. Use the documented
  rebuild pattern: create `<table>_new` with the full target schema, `INSERT INTO ... SELECT`, drop
  the old table, rename. `app/database/migrations.py` is where this pattern lives — do not hand-roll
  it again in a later epic.
- **Never skip the backup command.** Every task here that touches `robotinaia.db` starts its `Verify`
  block with a `cp robotinaia.db robotinaia.db.backup-step-NN` line — run it even when you are about
  to test against a copy, because it is also this task's *production* rollback target.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/db-schema-changes.md`.

---

## Tasks

### `E2-T1` — Fix `AlertEngine.UMBRAL_SENAL` `AttributeError`

**Depends on:** nothing · **Priority:** p0

`app/services/alert_engine.py`'s `get_recommendation` references `Settings.UMBRAL_SENAL`, which does
not exist — this throws in production today. `tests/test_alert.py` already encodes the intended
threshold: `get_recommendation(65) == "REVISAR"` and `get_recommendation(95) == "OPORTUNIDAD"`, and
the code's own `>= 50 → "REVISAR"` branch fixes the lower bound. `80` is the only value consistent
with both the tests and the codebase's round-decade convention (`50`) — add it as a plain class
attribute, do not touch `alert_engine.py` itself (its logic is already correct, only the referenced
constant is missing).

**Files**
- `app/core/settings.py` — edit: add `UMBRAL_SENAL = 80` next to the other numeric thresholds.

**Acceptance**

1. **WHEN** `pytest tests/test_alert.py` runs **THE SYSTEM SHALL** exit 0 with 5 passed, 0 failed.
2. **WHEN** `AlertEngine().get_recommendation(80)` is called **THE SYSTEM SHALL** return `"OPORTUNIDAD"`.
3. **WHEN** `AlertEngine().get_recommendation(79)` is called **THE SYSTEM SHALL** return `"REVISAR"`.

**Verify**

```bash
pytest tests/test_alert.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E2-T1: fix AlertEngine.UMBRAL_SENAL AttributeError"
git tag step-03-fix-umbral-senal
```

### `E2-T2` — Add `tests/conftest.py` DB isolation fixture

**Depends on:** nothing · **Priority:** p0

Add a `db_path(tmp_path, monkeypatch)` fixture: create an empty temp SQLite file, monkeypatch
`Settings.DATABASE_NAME` to point at it (matching how `connection.get_connection()` reads it fresh on
every call — no connection caching to fight), call `create_tables()` against it, yield the path. Not
autouse — tests that do not touch the DB (e.g. pure `binance_provider` unit tests) should not pay for
schema setup; request `db_path` explicitly where needed.

**Files**
- `tests/conftest.py` — new.

**Acceptance**

1. **WHEN** a test requests `db_path` and writes a row **THE SYSTEM SHALL** persist it only to the
   temp file, never to `robotinaia.db`.
2. **WHEN** `pytest tests/` runs the full suite **THE SYSTEM SHALL** exit 0 with no
   `sqlite3.OperationalError` about a locked or missing table.
3. **WHEN** two tests both request `db_path` **THE SYSTEM SHALL** give each its own isolated file.

**Verify**

```bash
sha1sum robotinaia.db > /tmp/before.sha1 2>/dev/null || echo no-db-yet > /tmp/before.sha1
pytest tests/ -q
sha1sum robotinaia.db > /tmp/after.sha1 2>/dev/null || echo no-db-yet > /tmp/after.sha1
diff /tmp/before.sha1 /tmp/after.sha1
```

**Checkpoint**

```bash
git add -A && git commit -m "E2-T2: add tests/conftest.py DB isolation fixture"
git tag step-04-conftest-db-isolation
```

### `E2-T3` — WAL mode + `busy_timeout` on every connection

**Depends on:** `E2-T2` · **Priority:** p0

In `get_connection()`, after `sqlite3.connect(Settings.DATABASE_NAME)`, execute
`PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA foreign_keys=ON` on every call.

**Files**
- `app/database/connection.py` — edit.
- `tests/test_connection.py` — new: opens two connections in separate threads, holds a write
  transaction briefly on one, asserts the other succeeds within the timeout instead of raising
  `database is locked`.

**Acceptance**

1. **WHEN** `get_connection()` is called **THE SYSTEM SHALL** return a connection with
   `PRAGMA journal_mode` reporting `wal`.
2. **WHEN** `get_connection()` is called **THE SYSTEM SHALL** return a connection with
   `PRAGMA busy_timeout` reporting `5000`.
3. **WHEN** two threads open connections concurrently and one holds a write transaction for 200ms
   **THE SYSTEM SHALL** have the second connection succeed once the first commits.
4. **WHEN** `PRAGMA foreign_keys` is queried on a fresh connection **THE SYSTEM SHALL** report `1`.

**Verify**

```bash
cp robotinaia.db robotinaia.db.backup-step-05 2>/dev/null || echo no-live-db
pytest tests/test_connection.py -v
sqlite3 robotinaia.db "PRAGMA journal_mode;"
```

**Checkpoint**

```bash
git add -A && git commit -m "E2-T3: WAL mode, busy_timeout, foreign_keys pragma on every connection"
git tag step-05-wal-busy-timeout
```

Rollback if needed: `cp robotinaia.db.backup-step-05 robotinaia.db`.

### `E2-T4` — Consolidate schema, add FK/CHECK constraints, `user_version` tracking

**Depends on:** `E2-T3` · **Priority:** p0

Move `SCHEMA_SCHEDULER_RUNS` (from `app/scheduler/repository.py`) and `SCHEMA_PAPER_POSITIONS` (from
`app/paper_trading/repository.py`) into `schema.py`'s `create_tables()`; both modules keep their
`crear_tabla()` as a thin call-through for backward compatibility. Add `stock_scheduler_runs` and
`alert_state` table definitions (used starting Epics 5/6). Add `app/database/migrations.py`:
`current_version(conn)` / `apply_migrations(conn)`, run by `create_tables()` after the base
`CREATE TABLE IF NOT EXISTS` block — additive on fresh DBs, rebuild-pattern on existing ones needing a
new CHECK. Add FK (`portfolio_decisions.position_id -> portfolio.id`) and CHECK
(`signals.signal`, `portfolio.status`) to columns that already exist today. **Do not** add
`asset_class`/`normalized_symbol` to `portfolio` here — that is Epic 4's job.

**Files**
- `app/database/schema.py` — edit.
- `app/database/migrations.py` — new.
- `app/scheduler/repository.py` — edit.
- `app/paper_trading/repository.py` — edit.

**Acceptance**

1. **WHEN** `sqlite3 robotinaia.db "PRAGMA foreign_key_check;"` runs after migration **THE SYSTEM
   SHALL** return no rows.
2. **WHEN** an `INSERT INTO portfolio_decisions` references a non-existent `portfolio.id`
   **THE SYSTEM SHALL** raise `sqlite3.IntegrityError`.
3. **WHEN** an `INSERT INTO signals` uses a `signal` value outside `('PENDING','EXECUTED','SOLD','EXPIRED')`
   **THE SYSTEM SHALL** raise `sqlite3.IntegrityError`.
4. **WHEN** `create_tables()` runs twice in a row **THE SYSTEM SHALL** be idempotent, `PRAGMA
   user_version` unchanged on the second run.
5. **WHEN** `sqlite3 robotinaia.db "PRAGMA user_version;"` runs **THE SYSTEM SHALL** report `>= 1`.

**Verify**

```bash
cp robotinaia.db robotinaia.db.backup-step-06
pytest tests/test_schema_constraints.py -v
sqlite3 robotinaia.db "PRAGMA foreign_key_check;"
sqlite3 robotinaia.db "PRAGMA user_version;"
```

**Checkpoint**

```bash
git add -A && git commit -m "E2-T4: consolidate schema, add FK/CHECK constraints, user_version tracking"
git tag step-06-schema-consolidation
```

Rollback if needed: `cp robotinaia.db.backup-step-06 robotinaia.db`.

### `E2-T5` — Migration script applying constraints to the live DB, row-count parity

**Depends on:** `E2-T4` · **Priority:** p0

`migrations/0000_apply_constraints.py`: counts rows per table before, runs `apply_migrations()`,
counts after, asserts equality per table, logs via `loguru`, exits 1 on mismatch (backup file from
this task's Verify remains for manual restore).

**Files**
- `migrations/0000_apply_constraints.py` — new.
- `tests/test_migration_row_counts.py` — new.

**Acceptance**

1. **WHEN** `python migrations/0000_apply_constraints.py` runs against a copy of the live DB
   **THE SYSTEM SHALL** report identical row counts per table before/after and exit 0.
2. **WHEN** run against a DB with an orphaned `portfolio_decisions` row (test fixture) **THE SYSTEM
   SHALL** exit 1 and report which row violates the new FK.
3. **WHEN** `pytest tests/test_migration_row_counts.py` runs **THE SYSTEM SHALL** exit 0.

**Verify**

```bash
cp robotinaia.db robotinaia.db.backup-step-07
cp robotinaia.db /tmp/robotinaia_migration_test.db 2>/dev/null || sqlite3 /tmp/robotinaia_migration_test.db "SELECT 1;"
python migrations/0000_apply_constraints.py
pytest tests/test_migration_row_counts.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E2-T5: migration script with row-count parity verification"
git tag step-07-migration-parity-verified
```

Rollback if needed: `cp robotinaia.db.backup-step-07 robotinaia.db`.

---

## Epic acceptance

1. **WHEN** the full test suite runs **THE SYSTEM SHALL** exit 0, including `test_alert.py` (now
   fixed) and every new test file in this epic.
2. **WHEN** `sqlite3 robotinaia.db "PRAGMA journal_mode;"` and `PRAGMA foreign_key_check;` run
   **THE SYSTEM SHALL** report `wal` and zero rows respectively.

```bash
pytest tests/ -q
sqlite3 robotinaia.db "PRAGMA journal_mode;"
sqlite3 robotinaia.db "PRAGMA foreign_key_check;"
```

## Pitfalls

- **`PRAGMA foreign_keys` is per-connection, not persistent.** Do not assume setting it once suffices.
- **Do not add `asset_class`/`normalized_symbol` in this epic** — that column belongs to Epic 4's
  migration (E4-T1), which owns the portfolio-unification data model. Adding it here would split one
  logical change across two epics' checkpoints.
- **Always back up before touching `robotinaia.db`**, even when the Verify command operates on a copy
  — the backup is this task's production rollback target, not test scaffolding.

## Before moving on

- [ ] All 5 tasks `done` in `tasks.json`.
- [ ] Every `Verify` command in this epic passed.
- [ ] Tags `step-03` through `step-07` (the five in this epic) exist.
- [ ] `robotinaia.db.backup-step-05`, `-06`, `-07` exist on disk (or a documented equivalent if this
      was run against a fresh, empty DB with nothing to back up).
- [ ] No file outside the subtree was modified.
