# Epic 05: Alert Reliability

> After this epic, stop-loss/target alert state survives process restart with an explicit
> first_trigger/periodic_reminder/new_extreme/resolved machine — the failure mode that let the stale
> BTC-USD position go unnoticed cannot recur for any future position.

| | |
|---|---|
| **Epic id** | `05-alert-reliability` |
| **Tasks** | `E5-T1` … `E5-T2` |
| **Depends on** | `04-unified-portfolio-and-pnl` (E4-T3) |
| **Unlocks** | nothing directly; `08-legacy-decommission` waits on the whole chain transitively |
| **Parallel with** | `06-scheduler-resilience` |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · SQLite via raw `sqlite3` · `loguru` · `pytest`.

| Task | Command |
|---|---|
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |

**Gate:** `pytest tests/test_alert_state.py tests/test_portfolio_alerts_state.py -v` passes before
either task here is marked done. No local service needed; `alert_state` table already exists (added
in Epic 2, `E2-T4`).

## Directory subtree

```
app/
  alerts/
    alert_state.py             # NEW (E5-T1)
    portfolio_alerts.py        # EDIT (E5-T2)
  core/
    settings.py                # EDIT (E5-T1) — ALERTA_RECORDATORIO_HORAS, ALERTA_CAMBIO_MATERIAL_PCT
tests/
  test_alert_state.py                # NEW (E5-T1)
  test_portfolio_alerts_state.py     # NEW (E5-T2)
```

## Data model touched here

| Entity | Fields this epic adds or reads | Notes |
|---|---|---|
| `alert_state` | reads/writes all columns — table was defined in Epic 2 (`E2-T4`), not created here | `UNIQUE(position_id, alert_type)` is what makes `record_trigger` safe to call every cycle |

## Contracts

**Consumed** — already exists, do not rebuild:

| From | Interface | Guarantee |
|---|---|---|
| `04-unified-portfolio-and-pnl` | `app/services/portfolio_service.get_open_positions()` | rows keyed by `portfolio.id`, which `alert_state.position_id` references |
| `02-database-integrity-and-concurrency` | `alert_state` table (schema) | already exists with its CHECK/UNIQUE constraints |
| `app/services/telegram_service.enviar_mensaje_telegram` | `(mensaje) -> código` | unchanged, used for every notification this epic sends |

**Produced**:

| Export | Signature | Used by |
|---|---|---|
| `app/alerts/alert_state.record_trigger` | `(position_id, alert_type, price, now=None) -> None` | `portfolio_alerts.py` |
| `app/alerts/alert_state.should_notify` | `(position_id, alert_type, now=None) -> bool` | `portfolio_alerts.py` |
| `app/alerts/alert_state.resolve` | `(position_id, alert_type) -> None` | `portfolio_alerts.py` |

## Conventions that bite in this area

- **`extreme_price` tracks the worst price for `stop_loss` alerts and the best price for `target`
  alerts** — direction matters and is easy to get backwards; test both directions explicitly.
- **The 6-hour reminder window and 0.5% material-change threshold are `Settings` class attributes**
  (`ALERTA_RECORDATORIO_HORAS`, `ALERTA_CAMBIO_MATERIAL_PCT`), not environment variables — matching
  how the repo already handles tunable constants (`TRAILING_STEP_PCT`, `INTERVALO_REVISION_MINUTOS`).
- **`portfolio.py`'s `alerta_stop_enviada` column and `marcar_alerta_stop` function are left alone.**
  They become dead weight on the legacy path once `portfolio_alerts.py` cuts over in `E5-T2`, but
  deleting them is Epic 8's job, not this epic's.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/spanish-docstrings-english-identifiers.md`.

---

## Tasks

### `E5-T1` — Add persisted alert state machine

**Depends on:** nothing beyond Epic 4 (already unlocked) · **Priority:** p0

`app/alerts/alert_state.py` implements `record_trigger`, `should_notify`, `resolve` against the
`alert_state` table. `record_trigger`: no existing row → insert `first_trigger`; existing row, price
within `ALERTA_CAMBIO_MATERIAL_PCT` of stored extreme → no status change; price worse than the
extreme by more than the threshold → `new_extreme`, update `extreme_price`. `should_notify`: `True`
for `first_trigger`/`new_extreme`; `True` for any non-`resolved` status once
`ALERTA_RECORDATORIO_HORAS` have elapsed since `last_notified_at` (transitioning it to
`periodic_reminder`); `False` otherwise. `resolve`: sets `status='resolved'`, `resolved_at`.

**Files**
- `app/alerts/alert_state.py` — new.
- `app/core/settings.py` — edit: add `ALERTA_RECORDATORIO_HORAS = 6`, `ALERTA_CAMBIO_MATERIAL_PCT = 0.5`.
- `tests/test_alert_state.py` — new.

**Acceptance**

1. **WHEN** `record_trigger` is called for a position/alert_type with no existing row **THE SYSTEM
   SHALL** insert `status='first_trigger'` and `should_notify` **THE SYSTEM SHALL** return `True`.
2. **WHEN** `record_trigger` is called again within 6 hours at a price within 0.5% of the stored
   extreme **THE SYSTEM SHALL** leave status unchanged and `should_notify` **THE SYSTEM SHALL** return
   `False`.
3. **WHEN** `record_trigger` is called with a price worse than the stored extreme by more than 0.5%
   **THE SYSTEM SHALL** set `status='new_extreme'` and `should_notify` **THE SYSTEM SHALL** return
   `True`.
4. **WHEN** more than 6 hours have elapsed since `last_notified_at` with no new extreme **THE SYSTEM
   SHALL** set `status='periodic_reminder'` and `should_notify` **THE SYSTEM SHALL** return `True`.
5. **WHEN** `resolve` is called **THE SYSTEM SHALL** set `status='resolved'`, `resolved_at` non-null,
   and a subsequent `record_trigger` **THE SYSTEM SHALL** start a fresh `first_trigger` cycle.

**Verify**

```bash
pytest tests/test_alert_state.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E5-T1: add persisted alert state machine"
git tag step-16-alert-state-machine
```

### `E5-T2` — Wire `portfolio_alerts.py` to the alert state machine

**Depends on:** `E5-T1` · **Priority:** p0

Replace `_revisar_stop_loss`'s `marcar_alerta_stop` bool flag with `alert_state.record_trigger` /
`should_notify` / `resolve` calls (`alert_type="stop_loss"`). Add the same wiring to
`_revisar_trailing_stop`'s target-hit path (`alert_type="target"`), without changing its existing
every-hit notify behavior (that path is not broken today — only stop-loss is).

**Files**
- `app/alerts/portfolio_alerts.py` — edit.
- `tests/test_portfolio_alerts_state.py` — new.

**Acceptance**

1. **WHEN** a position's price stays below `stop_loss` for two cycles more than 6 hours apart with no
   material change **THE SYSTEM SHALL** send exactly 2 Telegram notifications, not 0 (today's bug)
   and not one per cycle.
2. **WHEN** price moves to a new low below the stop by more than 0.5% between cycles **THE SYSTEM
   SHALL** send an immediate `new_extreme` notification regardless of the 6-hour window.
3. **WHEN** price recovers above `stop_loss` **THE SYSTEM SHALL** call `resolve`, and a subsequent
   breach **THE SYSTEM SHALL** notify immediately.

**Verify**

```bash
pytest tests/test_portfolio_alerts_state.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E5-T2: wire portfolio_alerts.py to persisted alert state machine"
git tag step-17-portfolio-alerts-state-wired
```

---

## Epic acceptance

1. **WHEN** a stop-loss condition persists across multiple scheduler cycles **THE SYSTEM SHALL**
   re-notify per the state machine's rules (immediate on new extreme, periodic otherwise), not fire
   once and go silent.
2. **WHEN** `pytest tests/` runs **THE SYSTEM SHALL** exit 0.

```bash
pytest tests/test_alert_state.py tests/test_portfolio_alerts_state.py -v
pytest tests/ -q
```

## Pitfalls

- **Get the extreme-tracking direction right per `alert_type`.** Stop-loss tracks the *lowest* price
  seen; target tracks the *highest*. A test that only exercises one direction will not catch the bug
  if the other is backwards.
- **Do not remove `portfolio.py`'s `marcar_alerta_stop`/`alerta_stop_enviada`.** That is Epic 8's job.

## Before moving on

- [ ] Both tasks `done` in `tasks.json`.
- [ ] `step-16-alert-state-machine` and `step-17-portfolio-alerts-state-wired` tags exist.
- [ ] No file outside the subtree was modified.
