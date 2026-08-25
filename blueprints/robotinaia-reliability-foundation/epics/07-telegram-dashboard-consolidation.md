# Epic 07: Telegram/Dashboard Consolidation

> After this epic, stock and crypto Telegram commands share one dispatch style backed by
> `portfolio_service.py`, `telegram_bot.py` registers only the unified module, and the Streamlit
> dashboard reads through a service function instead of inline SQL.

| | |
|---|---|
| **Epic id** | `07-telegram-dashboard-consolidation` |
| **Tasks** | `E7-T1` … `E7-T3` |
| **Depends on** | `04-unified-portfolio-and-pnl` (E4-T3, for `E7-T1`/`E7-T2`); `02-database-integrity-and-concurrency` (E2-T4, for `E7-T3`) |
| **Unlocks** | `08-legacy-decommission` (`E8-T2` needs `E7-T2` and `E7-T3` done) |
| **Parallel with** | nothing meaningfully — `E7-T3` can run any time after Epic 2, `E7-T1`/`E7-T2` are sequential and depend on Epic 4 |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · `python-telegram-bot` 22.8 · `streamlit` 1.59.2 · `pandas` 3.0.3 · `pytest`.

| Task | Command |
|---|---|
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |
| Run dashboard locally (manual smoke, not a Verify) | `streamlit run app/dashboard/dashboard.py` |

**Gate:** `pytest tests/test_commands.py tests/test_telegram_bot_registration.py
tests/test_signal_query_service.py -v` passes before any task here is marked done.

## Directory subtree

```
app/
  notifications/
    crypto_telegram_commands.py     # exists, read-only source for cripto_command's body — logic moves into commands.py
    commands.py                     # NEW (E7-T1)
  dashboard/
    dashboard.py                    # EDIT (E7-T3)
  services/
    signal_query_service.py         # NEW (E7-T3)
telegram_bot.py                     # EDIT (E7-T2)
telegram_commands.py                # exists, read-only reference — unregistered but not deleted here
tests/
  test_commands.py                       # NEW (E7-T1)
  test_telegram_bot_registration.py      # NEW (E7-T2)
  test_signal_query_service.py           # NEW (E7-T3)
```

## Data model touched here

NOT APPLICABLE — no schema change in this epic; `E7-T1`/`E7-T2` read/write `portfolio` through the
service layer built in Epic 4, `E7-T3` reads `signals` through a new query function with the same SQL
already in `dashboard.py` today.

## Contracts

**Consumed** — already exists, do not rebuild:

| From | Interface | Guarantee |
|---|---|---|
| `04-unified-portfolio-and-pnl` | `app/services/portfolio_service.{add_position,sell_position,get_open_positions,registrar_decision}` | the only portfolio mutation surface `commands.py` may call |
| `app/notifications/crypto_telegram_commands.cripto_command` | current body, `persistir=False` read-only behavior | moved verbatim into `commands.py`, not rewritten |
| `app/database/connection.get_connection()` | WAL/FK-ready connection | `signal_query_service.py` |

**Produced**:

| Export | Signature | Used by |
|---|---|---|
| `app/notifications/commands.COMMANDS` | `dict[str, Callable]` | `telegram_bot.py` registration |
| `app/services/signal_query_service.listar_senales` | `() -> pd.DataFrame` | `app/dashboard/dashboard.py` |

## Conventions that bite in this area

- **`cripto_command()`'s body must move unchanged.** It already does not touch the portfolio
  (`persistir=False`, read-only) — do not "improve" it while relocating it; that risks an unrelated
  behavior change slipping into a consolidation-only epic.
- **`telegram_commands.py` is not deleted here.** It becomes unregistered dead weight after `E7-T2`,
  removed only in Epic 8 after the observation-period gate.
- **`dashboard.py`'s `sys.path.insert(0, ...)` line at the top stays untouched** — it is already
  correct for running `streamlit run app/dashboard/dashboard.py` from any directory.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/spanish-docstrings-english-identifiers.md`.

---

## Tasks

### `E7-T1` — Add unified `app/notifications/commands.py`

**Depends on:** nothing beyond Epic 4 (already unlocked) · **Priority:** p0

`app/notifications/commands.py` exposes `portfolio_command()`, `comprar_command(...)` (renamed from
`buy_command`), `sell_command(...)`, `vender_command(...)`, `mantener_command(...)` (ported from
`telegram_commands.py`, rewritten against `portfolio_service` instead of `portfolio.py`),
`analisis_command(...)` (ported unchanged — never touches portfolio state), and `cripto_command()`
(moved as-is from `crypto_telegram_commands.py`). All seven collected in
`COMMANDS: dict[str, Callable]`.

**Scope correction (confirmed with the operator):** the original task text only named 5 functions,
which would have made E7-T2's "zero `telegram_commands` imports" criterion impossible without
silently dropping `/sell` and `/analisis` — real commands in the current bot this task's original
draft missed. `sell_command` and `analisis_command` are in scope here for exactly that reason.

**Files**
- `app/notifications/commands.py` — new.
- `tests/test_commands.py` — new.

**Acceptance**

1. **WHEN** `portfolio_command()` is called with open positions in both asset classes **THE SYSTEM
   SHALL** list both stock and crypto positions in one output.
2. **WHEN** `comprar_command` is called **THE SYSTEM SHALL** create a position via
   `portfolio_service.add_position`, not `portfolio.add_position`.
3. **WHEN** `cripto_command()` is called **THE SYSTEM SHALL** return output identical in shape to the
   current `crypto_telegram_commands.py` implementation.
4. **WHEN** `sell_command`/`analisis_command` are called **THE SYSTEM SHALL** behave the same as
   `telegram_commands.py`'s originals.

**Verify**

```bash
pytest tests/test_commands.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E7-T1: add unified app/notifications/commands.py"
git tag step-20-unified-commands
```

### `E7-T2` — Cut over `telegram_bot.py` to unified commands module

**Depends on:** `E7-T1` · **Priority:** p0

Update `telegram_bot.py`'s `CommandHandler` registrations to point at
`app/notifications/commands.py`'s functions instead of `telegram_commands.py`'s /
`crypto_telegram_commands.py`'s. Leave both old files on disk, unregistered.

**Files**
- `telegram_bot.py` — edit.
- `tests/test_telegram_bot_registration.py` — new.

**Acceptance**

1. **WHEN** `telegram_bot.py` is inspected **THE SYSTEM SHALL** show zero `import` statements
   referencing `telegram_commands` or `crypto_telegram_commands`.
2. **WHEN** the bot's registered command handlers are enumerated **THE SYSTEM SHALL** show
   `/portfolio`, `/comprar` (renamed from `/buy`), `/sell`, `/vender`, `/mantener`, `/analisis`,
   `/cripto` all pointing at `app.notifications.commands` functions.
3. **WHEN** `pytest tests/` runs the full suite **THE SYSTEM SHALL** exit 0.

**Verify**

```bash
pytest tests/test_telegram_bot_registration.py -v
pytest tests/ -q
```

**Checkpoint**

```bash
git add -A && git commit -m "E7-T2: cut over telegram_bot.py to unified commands module"
git tag step-21-telegram-bot-cutover
```

### `E7-T3` — Route dashboard through `signal_query_service`

**Depends on:** nothing beyond Epic 2 (already unlocked) · **Priority:** p1

Extract `dashboard.py`'s `cargar_senales()` query into
`app/services/signal_query_service.py::listar_senales() -> pd.DataFrame`, same SQL, same columns.
`dashboard.py` calls it instead of composing SQL inline. Zero layout/metric/visual change.

**Files**
- `app/dashboard/dashboard.py` — edit.
- `app/services/signal_query_service.py` — new.
- `tests/test_signal_query_service.py` — new.

**Acceptance**

1. **WHEN** `listar_senales()` is called against a fixture DB with 3 signals **THE SYSTEM SHALL**
   return a `DataFrame` with exactly 3 rows and columns `id, symbol, score, signal, price, timestamp`.
2. **WHEN** `dashboard.py`'s source is inspected **THE SYSTEM SHALL** show zero inline `SELECT`
   statements.
3. **WHEN** the dashboard boots against an empty DB **THE SYSTEM SHALL** render the "No existen
   señales todavía." warning path unchanged.

**Verify**

```bash
pytest tests/test_signal_query_service.py -v
! grep -q SELECT app/dashboard/dashboard.py
```

**Checkpoint**

```bash
git add -A && git commit -m "E7-T3: route dashboard through signal_query_service"
git tag step-22-dashboard-service-layer
```

---

## Epic acceptance

1. **WHEN** `/portfolio` is invoked against a DB with both a stock and a crypto position **THE
   SYSTEM SHALL** list both.
2. **WHEN** `pytest tests/` runs **THE SYSTEM SHALL** exit 0.

```bash
pytest tests/test_commands.py tests/test_telegram_bot_registration.py tests/test_signal_query_service.py -v
pytest tests/ -q
```

## Pitfalls

- **One-time manual diff, not a build gate:** compare `portfolio_command()`'s new output against the
  old `telegram_commands.py` output for the same DB state once, by eye — Telegram message formatting
  is not meaningfully unit-testable content (per blueprint §9.1's Parity checklist). This is the one
  documented exception to "everything is a script-decidable gate" in this blueprint, and it never
  blocks a task's `done` status.
- **Do not delete `telegram_commands.py` or `crypto_telegram_commands.py` in this epic.** That is
  Epic 8, after the observation period.

## Before moving on

- [ ] All 3 tasks `done` in `tasks.json`.
- [ ] Tags `step-20`, `step-21`, `step-22` exist.
- [ ] `telegram_bot.py` shows zero imports of the legacy command modules.
- [ ] No file outside the subtree was modified.
