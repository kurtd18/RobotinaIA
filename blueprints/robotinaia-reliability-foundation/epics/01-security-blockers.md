# Epic 01: Security Blockers

> After this epic, `.env.example` carries only placeholders, the leaked Telegram token is documented
> for operator-driven rotation, and a guard script prevents any real-looking secret from being
> committed again.

| | |
|---|---|
| **Epic id** | `01-security-blockers` |
| **Tasks** | `E1-T1` … `E1-T2` |
| **Depends on** | nothing — start here |
| **Unlocks** | nothing directly (independent of the functional epics), but must land first per the required build order |
| **Parallel with** | `02-database-integrity-and-concurrency` (E2-T1 only), `03-unified-market-data-provider` |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · SQLite (raw `sqlite3`, no ORM) · `loguru` for logging · `pytest` for tests. No package
manager beyond `pip` + `requirements.txt` (already pinned, nothing new added here).

| Task | Command |
|---|---|
| Install | `pip install -r requirements.txt` |
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |
| Init DB | `python init_db.py` |

**Gate:** `pytest tests/ -q` passes before either task here is marked done.

This epic touches no database and needs no local service.

## Directory subtree

```
.env.example              # EDIT — placeholders only
scripts/
  check_no_secrets.py     # NEW — secret-pattern guard
tests/
  test_check_no_secrets.py  # NEW — tests the guard script itself
```

Everything outside this subtree is out of scope for this epic.

## Data model touched here

NOT APPLICABLE — no database change in this epic.

## Contracts

**Consumed** — nothing; this epic has no dependency on prior work.

**Produced**:

| Export | Signature | Used by |
|---|---|---|
| `scripts/check_no_secrets.py` | CLI script, exit 0 (clean) / exit 1 (secret found) | operator's local pre-commit hook (documented, not wired automatically — no CI exists in this repo) |

## Conventions that bite in this area

- **This epic never touches real credentials programmatically.** Every credential-rotation action
  (BotFather token revoke, git history rewrite via `git filter-repo`) is an **operator instruction**,
  documented in this file, never executed by the build agent. If you find yourself about to run
  `git filter-repo` or touch a live `.env` file — stop. That is not this epic's job.
- `.env` is already correctly gitignored; do not touch `.gitignore` in this epic.
- The repo has no CI pipeline. "Add a CI guard" from the brief is satisfied by a plain script the
  operator can wire into `.git/hooks/pre-commit` locally — do not add a new CI framework.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/db-schema-changes.md` (not applicable
here — no DB touched),  `.claude/rules/spanish-docstrings-english-identifiers.md` (applies — write
docstrings in Spanish, identifiers in English, matching every existing file in this repo).

---

## Tasks

### `E1-T1` — Scrub `.env.example`, document token rotation

**Depends on:** nothing · **Priority:** p0

`.env.example:5-6` currently contains a real, live Telegram bot token
(`TELEGRAM_BOT_TOKEN=8712940547:AAGT...`, truncated here deliberately) and a real chat id
(`TELEGRAM_CHAT_ID=1059706281`), committed since `842c615`. Replace both with clear placeholders.
Do not touch `GEMINI_API_KEY=` (already empty, correct as-is).

This task is **code-only** — it edits the tracked example file. The actual token rotation (revoking
via `@BotFather`, updating the real untracked `.env`, scrubbing git history with `git filter-repo`,
redeploying on Railway) is listed below as **operator instructions**, not part of this task's
`Verify` — because it requires real Telegram/git/Railway access this build agent does not have and
must never simulate.

**Operator instructions (write these into the epic's PR/commit description or hand to the operator
directly — do not execute any of them):**

1. Open Telegram → `@BotFather` → `/revoke` (or `/token`) for the RobotinaIA bot → issue a new token.
2. Update the real, untracked `.env` with the new token.
3. Scrub history: `pip install git-filter-repo` then, substituting the actual leaked token value
   (recover it from `git log -p -- .env.example` if needed — deliberately not written out here so
   this file never carries the secret into git history itself):
   `git filter-repo --replace-text <(echo '<LEAKED_TOKEN_VALUE>==>REDACTED')`.
   This rewrites history — coordinate with any other clone, force-push only after confirming locally.
4. Redeploy on Railway with the new token set as an environment variable there.

**Files**
- `.env.example` — edit: replace the two real values with placeholders.

**Acceptance**

1. **WHEN** `grep -c '8712940547' .env.example` runs **THE SYSTEM SHALL** exit with status 1 (grep's
   not-found status).
2. **WHEN** `.env.example` is read **THE SYSTEM SHALL** show `TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here`
   and `TELEGRAM_CHAT_ID=your-telegram-chat-id-here` verbatim.
3. **WHEN** every `.py` file is grepped for the leaked token string **THE SYSTEM SHALL** return zero
   matches.

**Verify**

```bash
grep -c '8712940547' .env.example; test $? -eq 1
grep -q 'your-telegram-bot-token-here' .env.example
! grep -rn '8712940547' --include=*.py .
```

**Checkpoint**

```bash
git add -A && git commit -m "E1-T1: scrub .env.example, document token rotation"
git tag step-01-security-env-scrub
```

### `E1-T2` — Add secret-pattern guard script

**Depends on:** `E1-T1` · **Priority:** p0

Write `scripts/check_no_secrets.py`: a stdlib-only (`re`, `subprocess`, `sys`) scanner over tracked
and staged text files, matching secret-shaped patterns — Telegram bot tokens
(`\d{8,10}:[A-Za-z0-9_-]{35}`), generic `(api|secret|token)[_-]?key\s*[:=]\s*['"][A-Za-z0-9_\-]{20,}['"]`
assignments, and any non-placeholder value assigned in `.env.example` specifically. Exit 1 with the
offending `file:line` printed on any match, exit 0 otherwise. No new dependency — this is the "no new
heavyweight dependencies" convention applied literally.

**Files**
- `scripts/check_no_secrets.py` — new
- `tests/test_check_no_secrets.py` — new, exercises the script against a clean fixture and a
  deliberately-planted fixture

**Acceptance**

1. **WHEN** `python scripts/check_no_secrets.py` runs against the current repo **THE SYSTEM SHALL**
   exit 0.
2. **WHEN** a Telegram-token-shaped string is staged in a temp fixture file **THE SYSTEM SHALL** cause
   the script to exit 1 and print the fixture's path.
3. **WHEN** `.env.example` contains only placeholder values **THE SYSTEM SHALL** be reported clean by
   the script.

**Verify**

```bash
pytest tests/test_check_no_secrets.py
python scripts/check_no_secrets.py; test $? -eq 0
```

**Checkpoint**

```bash
git add -A && git commit -m "E1-T2: add secret-pattern guard script"
git tag step-02-secret-guard
```

---

## Epic acceptance

1. **WHEN** `grep -c '8712940547' .env.example; test $? -eq 1` runs **THE SYSTEM SHALL** exit 0
   (confirming the leak is gone).
2. **WHEN** `python scripts/check_no_secrets.py` runs **THE SYSTEM SHALL** exit 0.

```bash
pytest tests/test_check_no_secrets.py -v
python scripts/check_no_secrets.py; test $? -eq 0
grep -c '8712940547' .env.example; test $? -eq 1
```

## Pitfalls

- **Do not rotate the real token as part of this build.** The build agent has no Telegram/Railway
  access and must never fabricate having done so. The operator instructions above are the entire
  deliverable for that half of the work — write them clearly, do not execute them.
- **Do not run `git filter-repo` or any history-rewriting command.** That is exclusively an operator
  action per the brief.

## Before moving on

- [ ] Both tasks `done` in `tasks.json`.
- [ ] Both `Verify` blocks passed.
- [ ] `step-01-security-env-scrub` and `step-02-secret-guard` tags exist.
- [ ] Operator instructions for token rotation and history scrub are visible in this file (they are,
      above) and were **not** executed by the build agent.
- [ ] No file outside the subtree was modified.
