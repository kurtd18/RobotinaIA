# Epic 06: Scheduler Resilience

> After this epic, the stock scheduler thread has the same duplicate-run protection the crypto
> scheduler already has, and an unhandled exception no longer means it silently stops covering stocks
> forever while the service still looks healthy.

| | |
|---|---|
| **Epic id** | `06-scheduler-resilience` |
| **Tasks** | `E6-T1` … `E6-T2` |
| **Depends on** | `02-database-integrity-and-concurrency` (E2-T4, for the `stock_scheduler_runs` table) |
| **Unlocks** | nothing directly |
| **Parallel with** | `04-unified-portfolio-and-pnl`, `05-alert-reliability` |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · `loguru` · `pytest` · `threading` (stdlib).

| Task | Command |
|---|---|
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |

**Gate:** `pytest tests/test_stock_scheduler_repository.py tests/test_stock_scheduler_supervisor.py -v`
passes before either task here is marked done.

## Directory subtree

```
app/
  scheduler/
    repository.py                     # exists, read-only — the pattern to mirror
    crypto_scheduler.py               # exists, read-only — the resilience pattern already proven
    stock_scheduler_repository.py     # NEW (E6-T1)
    supervisor.py                     # NEW (E6-T2)
run_all.py                            # EDIT (E6-T2)
tests/
  test_stock_scheduler_repository.py   # NEW (E6-T1)
  test_stock_scheduler_supervisor.py   # NEW (E6-T2)
```

## Data model touched here

| Entity | Fields this epic adds or reads | Notes |
|---|---|---|
| `stock_scheduler_runs` | reads/writes all columns — table defined in Epic 2 (`E2-T4`), not created here | mirrors `scheduler_runs` exactly, separate table so stock/crypto windows never collide |

## Contracts

**Consumed** — already exists, do not rebuild:

| From | Interface | Guarantee |
|---|---|---|
| `app/scheduler/repository.intentar_registrar_ejecucion` | `(fecha, hora_programada) -> bool` | the exact shape `stock_scheduler_repository.py` ports 1:1 |
| `app/services/telegram_service.enviar_mensaje_telegram` | `(mensaje) -> código` | used by the supervisor's escalation alert |
| `02-database-integrity-and-concurrency` | `stock_scheduler_runs` table | already exists |

**Produced**:

| Export | Signature | Used by |
|---|---|---|
| `app/scheduler/supervisor.run_supervised` | `(target: Callable, name: str, max_restarts=5, backoff_base_seconds=30) -> None` | `run_all.py` |
| `app/scheduler/stock_scheduler_repository.intentar_registrar_ejecucion` | `(fecha, hora_programada) -> bool` | `main.py`'s stock scheduler loop (integration wiring beyond this epic's minimal scope — see Pitfalls) |

## Conventions that bite in this area

- **`stock_scheduler_runs` is a separate table from `scheduler_runs`, not a shared one.** Stock and
  crypto scheduler windows must never collide on the same `UNIQUE(fecha, hora_programada)` constraint.
- **The supervisor must never restart forever silently.** `max_restarts` is a hard cap; hitting it
  sends exactly one Telegram escalation and then stops trying — this is the single most important
  observability change in the whole blueprint (see blueprint §16).
- **Backoff must actually increase between attempts** (`backoff_base_seconds * 2 ** restart_count`),
  not a fixed sleep — otherwise a fast-failing bug hammers the scheduler (and, transitively, whatever
  external API it calls) in a tight loop.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/spanish-docstrings-english-identifiers.md`.

---

## Tasks

### `E6-T1` — Add stock scheduler idempotency table

**Depends on:** nothing beyond Epic 2 (already unlocked) · **Priority:** p0

Port `app/scheduler/repository.py`'s `intentar_registrar_ejecucion` shape 1:1 into
`app/scheduler/stock_scheduler_repository.py` against `stock_scheduler_runs`.

**Files**
- `app/scheduler/stock_scheduler_repository.py` — new.
- `tests/test_stock_scheduler_repository.py` — new.

**Acceptance**

1. **WHEN** `intentar_registrar_ejecucion("2026-08-15", "09:00")` is called twice **THE SYSTEM SHALL**
   return `True` the first time and `False` the second.
2. **WHEN** called for two different `hora_programada` values on the same `fecha` **THE SYSTEM SHALL**
   return `True` for both.

**Verify**

```bash
pytest tests/test_stock_scheduler_repository.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E6-T1: add stock scheduler idempotency table"
git tag step-18-stock-scheduler-idempotency
```

### `E6-T2` — Supervise stock scheduler thread, capped restart + Telegram escalation

**Depends on:** `E6-T1` · **Priority:** p0

`app/scheduler/supervisor.py`: `run_supervised(target, name, max_restarts=5,
backoff_base_seconds=30)` runs `target()` in a loop; on unhandled exception, logs via `loguru`, sleeps
`backoff_base_seconds * (2 ** restart_count)` (capped at e.g. 30 minutes), increments the counter,
restarts — until `max_restarts`, at which point it sends one Telegram escalation
(`enviar_mensaje_telegram`, including exception type/message and restart count) and stops. Rewrite
`run_all.py`'s `_iniciar_scheduler` to call `run_supervised(scheduler_module.main,
"stock_scheduler")` instead of its current bare try/except.

**Files**
- `app/scheduler/supervisor.py` — new.
- `run_all.py` — edit.
- `tests/test_stock_scheduler_supervisor.py` — new.

**Acceptance**

1. **WHEN** `target()` raises on its first 2 calls and succeeds on the 3rd **THE SYSTEM SHALL** call
   it exactly 3 times, with increasing sleep between attempts, and never send the escalation alert.
2. **WHEN** `target()` always raises **THE SYSTEM SHALL** call it exactly `max_restarts` times, then
   send exactly one Telegram escalation message and stop calling `target()` again.
3. **WHEN** the escalation fires **THE SYSTEM SHALL** include the exception type/message and the
   restart count in the Telegram message.
4. **WHEN** `run_all.py` starts **THE SYSTEM SHALL** launch the stock scheduler through
   `run_supervised`.

**Verify**

```bash
pytest tests/test_stock_scheduler_supervisor.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E6-T2: supervise stock scheduler thread, capped restart + Telegram escalation"
git tag step-19-stock-scheduler-supervised
```

---

## Epic acceptance

1. **WHEN** the stock scheduler's target function raises repeatedly beyond `max_restarts`
   **THE SYSTEM SHALL** escalate exactly once via Telegram and stop retrying — never silently dead,
   never retrying forever.
2. **WHEN** `pytest tests/` runs **THE SYSTEM SHALL** exit 0.

```bash
pytest tests/test_stock_scheduler_repository.py tests/test_stock_scheduler_supervisor.py -v
pytest tests/ -q
```

## Pitfalls

- **Wiring `stock_scheduler_repository.py` into `main.py`'s actual scheduler loop is out of this
  epic's minimal scope** if `main.py`'s loop structure needs non-trivial changes to call it — this
  epic guarantees the idempotency *primitive* exists and is tested; if integrating it into `main.py`
  turns out to need more than a few lines, note that explicitly rather than silently expanding this
  task past its 5-file limit, and treat any deeper integration as a small follow-up.
- **Do not make the supervisor retry forever.** That reproduces exactly the "looks healthy while
  broken" problem this epic exists to fix, just with extra log noise.

## Before moving on

- [ ] Both tasks `done` in `tasks.json`.
- [ ] `step-18-stock-scheduler-idempotency` and `step-19-stock-scheduler-supervised` tags exist.
- [ ] `run_all.py`'s stock thread launch goes through `run_supervised`, verified by inspection.
- [ ] No file outside the subtree was modified.
