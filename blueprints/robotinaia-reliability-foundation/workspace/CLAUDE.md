# CLAUDE.md — RobotinaIA

> **Brownfield note:** this repo has no `CLAUDE.md` today, so copying this file into the project root
> is a clean write, not a merge. If this blueprint is ever regenerated after a `CLAUDE.md` already
> exists at the project root, merge instead of overwriting — do not blindly clobber operator edits.

RobotinaIA is a personal trading/alert bot (BVC + international stocks + crypto via Binance) with a
Telegram bot as the primary UI and a read-only Streamlit dashboard. Single Railway process
(`run_all.py`), SQLite (`robotinaia.db`) via raw `sqlite3`, no ORM.

## Commands

| Task | Command |
|---|---|
| Install deps | `pip install -r requirements.txt` |
| Init/verify DB schema | `python init_db.py` |
| Run full test suite | `pytest tests/ -q` |
| Run one test file | `pytest tests/test_X.py -v` |
| Run stock scheduler + bot (local, 2 terminals) | `python main.py` and `python telegram_bot.py` |
| Run combined process (Railway-style, 1 terminal) | `python run_all.py` |
| Run dashboard locally | `streamlit run app/dashboard/dashboard.py` |
| Back up DB before any schema change | `cp robotinaia.db robotinaia.db.backup-step-NN` |
| Check schema constraints | `sqlite3 robotinaia.db "PRAGMA foreign_key_check;"` |
| Check journal mode | `sqlite3 robotinaia.db "PRAGMA journal_mode;"` |
| Check migration version | `sqlite3 robotinaia.db "PRAGMA user_version;"` |
| Secret-pattern guard | `python scripts/check_no_secrets.py` |

## Conventions (existing repo, do not break)

- **Spanish docstrings/comments, English identifiers.** Every existing module follows this — new code
  must too.
- **Raw SQL via `sqlite3`, no ORM.** Do not introduce SQLAlchemy, Django ORM, or similar.
- **`loguru` for all logging** — `logger.info`/`logger.warning`/`logger.exception`, not `print`.
- **No heavyweight new dependencies.** Every step in this blueprint uses only what is already in
  `requirements.txt`.
- **`app.` import prefix, project root on `sys.path`** — tests and scripts run from the project root.
- **Constants live on `Settings` (`app/core/settings.py`), not as bare module-level literals** — see
  `TRAILING_STEP_PCT`, `INTERVALO_REVISION_MINUTOS` for the existing pattern.

## Database rules

- **Never touch `robotinaia.db` in a test.** Every DB-touching test requests the `db_path` fixture
  from `tests/conftest.py` (temp SQLite file, schema pre-created).
- **Back up `robotinaia.db` before any schema-changing command**, always:
  `cp robotinaia.db robotinaia.db.backup-step-NN`. Restore with the mirrored `cp` in reverse.
- **`PRAGMA foreign_keys` must be reissued on every connection** — SQLite does not persist it. See
  `app/database/connection.py`.
- **Table definitions live in `app/database/schema.py` only.** Never declare a `CREATE TABLE` in a
  repository module.

## Security

- **`.env` is gitignored and never committed.** `.env.example` must only ever contain placeholders —
  verify with `python scripts/check_no_secrets.py` before any commit that touches it.
- **No credential is ever handled programmatically by an agent.** Token rotation, git-history
  scrubbing (`git filter-repo`), and closing a real financial position are operator-only actions,
  documented as instructions, never executed by an agent session.

## This blueprint (`blueprints/robotinaia-reliability-foundation/`)

25 build steps across 8 epics — see `blueprints/robotinaia-reliability-foundation/tasks.json` for the
resumable DAG and `blueprints/robotinaia-reliability-foundation/epics/*.md` for per-task detail. Every
DB-schema-touching step backs up `robotinaia.db` first and states its rollback explicitly. The bundle
directory itself (`blueprints/robotinaia-reliability-foundation/`) is excluded from test discovery and
linting — see that epic's own `Verify` commands, none of which target files under `blueprints/`.

## Deployment

Railway, Nixpacks (no Dockerfile), single process `run_all.py`, single persistent volume holding
`robotinaia.db` (+ `robotinaia.db-wal`/`-shm` sidecar files once WAL mode is live — confirm Railway's
volume persists all three before relying on it in production).
