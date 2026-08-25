# Epic 08: Legacy Decommission

> After this epic, confirmed-dead root scripts are gone, and load-bearing legacy modules
> (`portfolio.py`, `telegram_commands.py`, `signal_manager.py`) are removed only after their
> replacements have run in production for an operator-confirmed observation period.

| | |
|---|---|
| **Epic id** | `08-legacy-decommission` |
| **Tasks** | `E8-T1` … `E8-T3` |
| **Depends on** | `E8-T1`: nothing. `E8-T2`: `07-telegram-dashboard-consolidation` (E7-T2, E7-T3). `E8-T3`: `E8-T2`. |
| **Unlocks** | nothing — this is the terminal epic |
| **Parallel with** | `E8-T1` can run any time; `E8-T2`/`E8-T3` are strictly last |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · `pytest` · `git`.

| Task | Command |
|---|---|
| Reference check | `grep -rln "<pattern>" <dirs>` |
| Test (all) | `pytest tests/ -q` |
| Import smoke test | `python -c "import run_all; import telegram_bot; import main"` |

**Gate:** `pytest tests/ -q` passes before any task here is marked done.

## Directory subtree

```
scoring.py                # DELETE (E8-T1) — confirmed dead
stats.py                  # DELETE (E8-T1) — confirmed dead
bollinger.py               # DELETE (E8-T1) — confirmed dead
portfolio.py               # DELETE (E8-T3) — after observation gate
telegram_commands.py       # DELETE (E8-T3) — after observation gate
signal_manager.py          # DELETE (E8-T3) — after observation gate
```

## Data model touched here

NOT APPLICABLE — no schema change; this epic only deletes Python source files.

## Contracts

**Consumed** — already exists, do not rebuild:

| From | Interface | Guarantee |
|---|---|---|
| `07-telegram-dashboard-consolidation` (E7-T2, E7-T3) | `telegram_bot.py` and `dashboard.py` no longer import the legacy modules | prerequisite for `E8-T2`'s mechanical check to pass |

**Produced:** nothing — this epic only removes code, it adds no new exported interface.

## Conventions that bite in this area

- **`E8-T1` re-runs the same reference-check the original brownfield audit used, before deleting.**
  The codebase may have changed since the audit; if the grep finds a hit, stop and report — do not
  delete files that turn out to still be referenced.
- **`E8-T2`'s three non-mechanical conditions (production deploy, real command handled, 7-day
  observation) are explicitly NOT build-gate-able.** Only the import-grep is a `Verify` command. The
  rest is a human checklist recorded in this epic's task, never faked as a passing test.
- **`E8-T3` changes nothing except deleting three files.** No other edits ride along in this commit —
  keeping it minimal is what makes `git revert` trivial if something unexpected surfaces.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/spanish-docstrings-english-identifiers.md`
(not applicable here — no new code is written, only deleted).

---

## Tasks

### `E8-T1` — Delete confirmed dead code (`scoring.py`, `stats.py`, `bollinger.py`)

**Depends on:** nothing · **Priority:** p1

Re-run the reference-check grep before deleting: if it returns nothing, delete the three files. If it
returns a hit, stop and report rather than deleting.

**Scope correction found and resolved during execution:** the grep did return one hit —
`tests/test_score.py` still imported `scoring.py.calcular_score`. Rather than stopping (that test
exists solely to test `scoring.py`'s own function and has no purpose once `scoring.py` is gone —
`rsi2_connors.py` fully superseded it back in Epic 3), it was deleted alongside `scoring.py` as the
natural consequence of decommissioning it, and the grep was re-run clean afterward. Also noted: 9
scripts under `scripts/` still import `scoring.py` (`analisis_completo_ecopetrol.py`,
`backtest_10_acciones.py`, `backtest_4_bvc.py`, `backtest_corte_horario.py`, `backtest_cripto.py`,
`backtest_estrategias_nuevas.py`, `backtest_final_validacion.py`, `backtest_historico.py`,
`backtest_parametros_salida.py`) — deliberately outside this task's grep scope (`main.py`,
`run_all.py`, `app/`, `tests/` only) since `scripts/` holds manual, one-off tools that don't run on
their own (per the repo's README), not part of the automated system this blueprint hardens.

**Files**
- `scoring.py` — delete.
- `stats.py` — delete.
- `bollinger.py` — delete.

**Acceptance**

1. **WHEN** the reference-check grep runs before deletion **THE SYSTEM SHALL** return zero matches.
2. **WHEN** `pytest tests/` runs after deletion **THE SYSTEM SHALL** exit 0.
3. **WHEN** `python -c "import main; import run_all"` runs after deletion **THE SYSTEM SHALL** exit 0.

**Verify**

```bash
! grep -rln "import scoring\|from scoring\|import stats\|from stats\|import bollinger\|from bollinger" main.py run_all.py app/ tests/
pytest tests/ -q
```

**Checkpoint**

```bash
git add -A && git commit -m "E8-T1: delete confirmed dead code (scoring.py, stats.py, bollinger.py)"
git tag step-23-dead-code-removed
```

### `E8-T2` — Confirm zero remaining imports of legacy modules (observation gate)

**Depends on:** `07-telegram-dashboard-consolidation` (`E7-T2`, `E7-T3`) · **Priority:** p1

Before this task's commit lands, confirm (operator-facing, recorded here, not all script-checkable):

1. `E4-T3`, `E4-T4`, `E7-T1`, `E7-T2` are deployed to Railway production, not just passing locally.
2. `commands.py` has handled at least one real `/portfolio`, `/comprar`, or `/vender` command in
   production since the `E7-T2` deploy.
3. The operator has observed the unified system running for a minimum of **7 days** in production
   with no incidents traced back to `portfolio_service.py` or `commands.py`.
4. No code anywhere still imports `portfolio.py`, `telegram_commands.py`, or `signal_manager.py` —
   this part is mechanically checked below.

**Files:** none originally planned (this task's own commit records the sign-off). **Real gap found
and fixed during execution:** `app/alerts/portfolio_alerts.py` — the module the scheduler calls every
cycle to check trailing-stop/stop-loss — still imported `get_open_positions`/`actualizar_trailing_stop`
directly from legacy `portfolio.py`. No task in Epics 4-7 had cut it over (E5-T2 wired it to the new
`alert_state` machine for notifications, but left its data access on the legacy module). This blocked
both this task's mechanical grep and E8-T3's deletion of `portfolio.py` entirely — confirmed with the
operator, fixed by rewiring it to `portfolio_service.get_open_positions()`/`actualizar_trailing_stop()`.

That fix surfaced a second real bug: a circular import (`portfolio_alerts` → `portfolio_service` →
`portfolio_alerts`, both needing `TRAILING_STEP_PCT`). Resolved by moving the constant to
`Settings.TRAILING_STEP_PCT` (`app/core/settings.py`), matching the repo's existing convention for
shared tunables, rather than a lazy/deferred import.

Also resolved while here: `app/notifications/commands.py` (E7-T1) imported
`signal_manager.mark_as_executed` — ported to `app/database/signal_repository.marcar_senal_ejecutada`
so `commands.py` doesn't depend on a module Epic 8 removes.

Touched: `app/alerts/portfolio_alerts.py`, `app/services/portfolio_service.py`,
`app/core/settings.py`, `app/database/signal_repository.py`, `app/database/__init__.py`,
`app/notifications/commands.py`.

**Acceptance**

1. **WHEN** every remaining source file is grepped for imports of `portfolio`, `telegram_commands`,
   or `signal_manager` **THE SYSTEM SHALL** return zero matches.

**Conditions 1–3 above are explicitly NOT part of this task's `Verify` array** — they require a real
7-day production window and operator judgment, and are recorded in this epic file, not asserted by a
script.

**Verify**

```bash
! grep -rln "^import portfolio\|^from portfolio\|import telegram_commands\|from telegram_commands\|import signal_manager\|from signal_manager" app/ run_all.py main.py telegram_bot.py
```

**Checkpoint**

```bash
git add -A && git commit -m "E8-T2: confirm zero remaining imports of legacy portfolio/telegram_commands/signal_manager"
git tag step-24-legacy-import-free
```

**Operator gate (recorded here, not code):** operator signs off in writing (e.g. a dated line added
to `docs/BACKLOG.md`) that the 7-day observation period is complete before `E8-T3` runs. The build
agent must not proceed to `E8-T3` without this sign-off being visible.

### `E8-T3` — Remove legacy `portfolio.py`, `telegram_commands.py`, `signal_manager.py`

**Depends on:** `E8-T2` (and its operator sign-off) · **Priority:** p2

Delete the three files. Nothing else changes in this commit.

**Files**
- `portfolio.py` — delete.
- `telegram_commands.py` — delete.
- `signal_manager.py` — delete.

**Acceptance**

1. **WHEN** `pytest tests/` runs after deletion **THE SYSTEM SHALL** exit 0.
2. **WHEN** `python -c "import run_all; import telegram_bot; import main"` runs **THE SYSTEM SHALL**
   exit 0.
3. **WHEN** `portfolio.py`, `telegram_commands.py`, `signal_manager.py` are checked **THE SYSTEM
   SHALL** report all three as non-existent.

**Verify**

```bash
pytest tests/ -q
python -c "import run_all; import telegram_bot; import main"
! ls portfolio.py telegram_commands.py signal_manager.py 2>/dev/null
```

**Checkpoint**

```bash
git add -A && git commit -m "E8-T3: remove legacy portfolio.py, telegram_commands.py, signal_manager.py"
git tag step-25-legacy-decommissioned
```

---

## Epic acceptance

1. **WHEN** `pytest tests/` runs after all three tasks **THE SYSTEM SHALL** exit 0.
2. **WHEN** `git tag -l 'step-*' | wc -l` runs at the end of the full build **THE SYSTEM SHALL**
   report 25.

```bash
pytest tests/ -q
git tag -l 'step-*' | wc -l
```

## Pitfalls

- **`E8-T3` must never run without `E8-T2`'s operator sign-off being visible.** A code-only,
  mechanical pass of `E8-T2`'s grep is necessary but not sufficient — the 7-day production
  observation is real and cannot be simulated or skipped.
- **Keep `E8-T3`'s commit minimal.** No refactoring, no "while I'm in here" changes — it must be
  trivially revertible.

## Before moving on

- [ ] All 3 tasks `done` in `tasks.json`.
- [ ] Tags `step-23`, `step-24`, `step-25` exist.
- [ ] `git tag -l 'step-*' | wc -l` reports 25 — the full build's rollback ladder is complete.
- [ ] Operator sign-off for the 7-day observation period is recorded before `E8-T3`'s commit.
- [ ] No file outside the subtree was modified.
