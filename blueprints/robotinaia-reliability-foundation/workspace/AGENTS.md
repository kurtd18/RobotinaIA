# AGENTS.md — RobotinaIA

Tool-neutral instructions for any agent (Claude Code or otherwise) working this build. If you are
Claude Code, `CLAUDE.md` in this same directory carries the same content in Claude-specific framing —
read either, they agree.

## What this project is

RobotinaIA: a personal trading/alert bot for BVC stocks, international stocks, and crypto (Binance).
Telegram bot is the primary UI; a read-only Streamlit dashboard exists alongside it. Deploys to
Railway as a single process (`run_all.py`). Data layer: SQLite via raw `sqlite3`, no ORM.

## Commands

```
pip install -r requirements.txt      # install
python init_db.py                    # create/verify schema (idempotent)
pytest tests/ -q                     # full test suite
pytest tests/test_X.py -v            # one test file
python scripts/check_no_secrets.py   # secret-pattern guard
```

## Rules for this build

1. **Never execute a credential-rotation or history-rewrite command.** `git filter-repo`, BotFather
   token revocation, and closing a real financial position are operator-only actions. If a step's
   instructions describe one, treat it as documentation to hand to a human, not a command to run.
2. **Back up `robotinaia.db` before any schema-changing command.**
   `cp robotinaia.db robotinaia.db.backup-step-NN`, matching the step number in
   `blueprints/robotinaia-reliability-foundation/tasks.json`.
3. **Every DB-touching test uses the `db_path` fixture from `tests/conftest.py`** — never operate
   against the live `robotinaia.db` from a test.
4. **Spanish docstrings/comments, English identifiers** — match the existing codebase's convention in
   every new file.
5. **No ORM, no heavyweight new dependency.** Everything in this blueprint is built from what is
   already in `requirements.txt`.
6. **Follow `blueprints/robotinaia-reliability-foundation/tasks.json`'s array order.** It is already
   in build order — do not re-rank by priority or by what looks quick.
7. **One commit, one tag, per task** — `git tag <checkpoint value from tasks.json>` immediately after
   each task's `Verify` array passes, before starting the next task.
