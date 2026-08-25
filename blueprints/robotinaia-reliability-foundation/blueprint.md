# RobotinaIA — Reliability Foundation (Brownfield Change Blueprint)

> BROWNFIELD change blueprint. This is not a new project — it evolves an existing, running Python
> trading/alert bot into a reliable, maintainable decision-support platform. No new strategies, no
> scoring changes, no UI redesign, no infra move.

---

## 1. Project Overview & Non-Goals

**Project:** RobotinaIA — a personal trading/alert bot for BVC (Colombian stock exchange),
international stocks (via Mercado Global Colombiano), and crypto (via Binance public APIs). Primary
UI is a Telegram bot; a read-only Streamlit dashboard exists alongside it. Deploys to Railway
(Nixpacks, no Dockerfile) as a single process (`run_all.py`) running three concurrent threads: stock
scheduler, crypto scheduler, Telegram polling loop. Data layer is SQLite (`robotinaia.db`) via raw
`sqlite3`, no ORM.

**Target user:** solo operator (the repo owner). Personal decision support, not a multi-user SaaS.

**Goal of this change:** reliability before features. Fix what is broken or fragile today, unify two
parallel code paths that grew independently (stock vs. crypto), and put a real safety net under the
database and the schedulers — without rewriting anything that already works.

### Current state (brownfield baseline)

- `app/services/alert_engine.py`'s `AlertEngine.get_recommendation` references
  `Settings.UMBRAL_SENAL`, which does not exist in `app/core/settings.py` — throws `AttributeError`
  in production today. `tests/test_alert.py` already encodes the intended threshold semantics and
  currently fails.
- `app/database/schema.py` has no foreign keys, no check constraints, `journal_mode=delete` (not
  WAL), no `busy_timeout`. Three tables (`scheduler_runs`, `paper_positions`, and — once added —
  the stock scheduler's own idempotency table) are declared ad hoc in their own modules instead of
  centrally in `schema.py`. No `PRAGMA user_version` migration tracking.
- Crypto has `BinanceProvider` (retry/backoff, 429/418 handling) implementing `MarketDataProvider`.
  Stocks call `yfinance` directly from `app/strategies/rsi2_connors.py` with zero retry logic.
- Two disconnected portfolio representations: the root `portfolio.py` (`portfolio` /
  `portfolio_decisions` tables, used by `app/alerts/portfolio_alerts.py` for stocks **and** a
  manually tracked `BTC-USD` position, id=2, still `OPEN`) and `app/paper_trading/repository.py`'s
  `paper_positions` table (Binance-style `BTCUSDT` symbols), used by the crypto engine. They never
  talk to each other.
- `portfolio.py`'s P&L (`sell_position`) ignores fees entirely.
- `app/alerts/portfolio_alerts.py`'s stop-loss alert (`marcar_alerta_stop`) fires once and never
  re-notifies unless price recovers above the stop first — this is why the stuck `BTC-USD` position
  went unnoticed.
- `run_all.py`'s stock-scheduler thread wraps its target in try/except, but on an unhandled
  exception the thread dies silently and permanently; the Telegram thread keeps running, so the
  service looks healthy while stock alerts have stopped. The crypto scheduler
  (`app/scheduler/crypto_scheduler.py`) already isolates per-symbol/per-cycle failures and has an
  idempotency table (`scheduler_runs`).
- Command handling is split: `telegram_commands.py` (stocks + legacy portfolio) and
  `app/notifications/crypto_telegram_commands.py` (crypto only), two different styles. The Streamlit
  dashboard (`app/dashboard/dashboard.py`) runs raw SQL against `signals` directly.
- **Confirmed dead code** (no imports anywhere in `main.py`/`run_all.py`/`app/`): root
  `scoring.py`, `stats.py`, `bollinger.py`.
- **Load-bearing legacy** (in active use today, must not be deleted before its replacement ships):
  root `portfolio.py`, `telegram_commands.py`, `signal_manager.py`.
- `tests/` has 24 files, one per module, **no `conftest.py`** — every test that touches the DB layer
  today risks touching the real `robotinaia.db` if not careful.
- **SECURITY: a live Telegram bot token is committed** in `.env.example:5` at repo root
  (`TELEGRAM_BOT_TOKEN=8712940547:AAGT...`), present in git history since commit `842c615`. `.env`
  itself is correctly gitignored; `.env.example` is not, and never should have carried a real value.

### Target state

- `Settings.UMBRAL_SENAL` exists, `AlertEngine` classifies correctly, `tests/test_alert.py` passes.
- SQLite runs WAL journal mode with `busy_timeout` set on every connection; FK constraints
  (`PRAGMA foreign_keys=ON`) and CHECK constraints on enum-like columns; every table defined once,
  centrally, in `schema.py`; `PRAGMA user_version` tracks applied migrations.
- `YahooProvider` implements `MarketDataProvider` with the same retry/backoff shape as
  `BinanceProvider`; `rsi2_connors.py` calls it instead of `yfinance` directly. RSI(2)-Connors scoring
  math is untouched.
- One portfolio table (`portfolio`, extended with `asset_class` and a normalized-symbol field) and
  one `app/services/portfolio_service.py` owning buy/sell/trailing-stop/P&L for both asset classes.
  The stale `BTC-USD` position is resolved (operator-chosen path, see Epic 4). Migration is
  data-preserving with a row-count-parity verify.
- `FeeConfig` strategy interface per asset class, defaulting to `fee_pct=0, configured=False`; every
  P&L output surfaces whether fees were included.
- Alert state persisted (`alert_state` table) with an explicit status machine
  (`first_trigger` / `periodic_reminder` / `new_extreme` / `resolved`), configurable re-notify
  interval (default 6h) and material-change threshold (default 0.5%).
- Stock scheduler thread supervised: catch, log, restart with backoff, capped restart count before
  escalating a Telegram alert; stock scheduler gets its own idempotency table mirroring
  `scheduler_runs`.
- One command-handling style under `app/notifications/`, stock and crypto both calling
  `portfolio_service.py`. Dashboard reads through a service layer, not raw SQL.
- Dead code deleted. Load-bearing legacy modules removed only after their replacements are built,
  tested, running in production, and the operator confirms an observation period.
- `.env.example` carries placeholders only; the real token is rotated (operator action) and git
  history scrubbed (operator action); a secret-pattern guard script prevents recurrence.

### Delta (what actually changes)

| Area | Current | Target | Type |
|---|---|---|---|
| `.env.example`, git history | real token committed | placeholders, token rotated, history scrubbed | SECURITY BLOCKER |
| `app/core/settings.py`, `alert_engine.py` | `UMBRAL_SENAL` missing, `AttributeError` | threshold defined, tests pass | PRODUCTION-RISK FIX |
| `app/database/schema.py`, `connection.py` | no FK/CHECK, no WAL, scattered schemas | WAL, FK/CHECK, single schema source, versioned migrations | ARCHITECTURAL MIGRATION |
| `app/strategies/rsi2_connors.py` | direct `yfinance` calls | `YahooProvider` via `MarketDataProvider` | ARCHITECTURAL MIGRATION |
| `portfolio.py` + `app/paper_trading/repository.py` | two disconnected models | one `portfolio_service.py`, one table | ARCHITECTURAL MIGRATION |
| BTC-USD id=2 stale position | stuck OPEN, unmanaged | resolved (operator decision) | PRODUCTION-RISK FIX |
| P&L calc | ignores fees | `FeeConfig`, `fees_included` flag | ARCHITECTURAL MIGRATION |
| `app/alerts/portfolio_alerts.py` | fire-once stop alert | persisted state machine, re-notify | ARCHITECTURAL MIGRATION |
| `run_all.py` stock thread | dies silently forever | supervised, capped restart, escalation | ARCHITECTURAL MIGRATION |
| `telegram_commands.py` + `crypto_telegram_commands.py` | two styles | one style under `app/notifications/` | ARCHITECTURAL MIGRATION |
| `app/dashboard/dashboard.py` | raw SQL | service-layer reads | ARCHITECTURAL MIGRATION |
| root `scoring.py`, `stats.py`, `bollinger.py` | dead, present | deleted | ARCHITECTURAL MIGRATION (decommission) |
| root `portfolio.py`, `telegram_commands.py`, `signal_manager.py` | load-bearing | deleted after observation period | ARCHITECTURAL MIGRATION (decommission) |
| `tests/` | no `conftest.py` | DB-isolation fixture, new coverage on P&L/trailing-stop/alert state/migration parity | ARCHITECTURAL MIGRATION (test infra) |

### Interfaces held constant

- `MarketDataProvider.get_stock(symbol) -> Stock` — unchanged contract; `YahooProvider` implements it
  exactly like `BinanceProvider` does.
- `enviar_mensaje_telegram(mensaje) -> código` (`app/services/telegram_service.py`) — unchanged, every
  new notification path uses it as-is.
- RSI(2)-Connors entry/exit math in `rsi2_connors.py` (`_hubo_cruce_entrada_hoy`,
  `_hubo_condicion_salida_hoy`) — unchanged, only its data source moves.
- Crypto scoring engine (`app/scoring/crypto_scoring_engine.py`) and crypto pipeline
  (`app/scheduler/crypto_pipeline.py`) — untouched by this blueprint; only the *portfolio/paper
  trading* side of crypto is touched (item 5's migration), not the scoring/analysis side.
- Deployment target (Railway, Nixpacks, single `run_all.py` process, single SQLite file) — unchanged.
- `python-telegram-bot` polling model, `schedule` library for the stock scheduler — unchanged.

### Non-Goals (explicitly out of scope for this blueprint)

- **New trading strategies or indicators** — FUTURE IMPROVEMENT, not evaluated here.
- **Changing existing scoring/indicator math or thresholds** — RSI(2)-Connors, crypto scoring engine
  weights, and `AlertEngine`'s `REVISAR`/`NO COMPRAR` bands are untouched; the one number this
  blueprint adds (`UMBRAL_SENAL`) is a bug fix restoring an already-intended value, not a new
  decision (see Epic 1, Step 2 rationale).
- **Moving off Railway or off SQLite** — FUTURE IMPROVEMENT if Railway's volume model or SQLite's
  single-writer model ever becomes the actual bottleneck; not evaluated here.
- **Migrating to PostgreSQL** — FUTURE IMPROVEMENT. The unified `portfolio_service.py` (Epic 4) is
  written against a small repository-style interface precisely so this becomes possible later
  without touching call sites, but no Postgres code is written in this blueprint.
- **Redesigning the Streamlit dashboard's UI/UX** — Epic 7 only changes *how the dashboard fetches
  data* (service layer instead of raw SQL), not its layout, its metrics, or its visual design.
- **Multi-user/multi-tenant support** — this remains a single-operator system; no user model, no
  auth, no per-user data isolation is added.
- **Real fee-rate configuration** (actual commission/spread/tax numbers) — FUTURE IMPROVEMENT. Epic 4
  ships the `FeeConfig` *interface* with `fee_pct=0, configured=False`; entering the operator's real
  fee schedule is a follow-up the operator does directly in configuration once this ships, not a
  business decision this blueprint makes.

---

## 2. Design System

NOT APPLICABLE — no UI is introduced or redesigned. The Telegram command style is unified in Epic 7,
but message formatting mirrors the existing style already used in `rsi2_connors.py` and
`portfolio_alerts.py` (Spanish labels, `f"..."` blocks with emoji headers) — no new visual system.

---

## 3. Directory Structure

```
RobotinaIA/
├── run_all.py                      # EDIT — supervisor wraps stock thread (Epic 6)
├── main.py                         # unchanged — stock scheduler loop entry point
├── telegram_bot.py                 # unchanged — Telegram polling entry point
├── init_db.py                      # unchanged — calls app.database.schema.create_tables()
├── portfolio.py                    # DEPRECATED — removed in Epic 8, step 24-25
├── telegram_commands.py            # DEPRECATED — removed in Epic 8, step 24-25
├── signal_manager.py               # DEPRECATED — removed in Epic 8, step 24-25
├── scoring.py                      # DEAD — removed in Epic 8, step 23
├── stats.py                        # DEAD — removed in Epic 8, step 23
├── bollinger.py                    # DEAD — removed in Epic 8, step 23
├── .env.example                    # EDIT — placeholders only (Epic 1, step 1)
├── scripts/
│   └── check_no_secrets.py         # NEW — secret-pattern guard (Epic 1, step 2)
├── app/
│   ├── core/
│   │   └── settings.py             # EDIT — adds UMBRAL_SENAL (Epic 1, step 3... see numbering below)
│   ├── database/
│   │   ├── connection.py           # EDIT — WAL, busy_timeout, foreign_keys ON (Epic 2)
│   │   ├── schema.py               # EDIT — consolidated schema, FK/CHECK, user_version (Epic 2)
│   │   └── migrations.py           # NEW — versioned migration runner (Epic 2)
│   ├── providers/
│   │   ├── market_data_provider.py # unchanged — ABC contract
│   │   ├── binance_provider.py     # unchanged — reference implementation
│   │   └── yahoo_provider.py       # NEW — Epic 3
│   ├── strategies/
│   │   └── rsi2_connors.py         # EDIT — uses YahooProvider (Epic 3)
│   ├── services/
│   │   ├── alert_engine.py         # unchanged code — fix is in settings.py (Epic 1)
│   │   ├── fee_config.py           # NEW — Epic 4
│   │   └── portfolio_service.py    # NEW — Epic 4
│   ├── alerts/
│   │   ├── portfolio_alerts.py     # EDIT — uses alert state machine (Epic 5)
│   │   └── alert_state.py          # NEW — Epic 5
│   ├── scheduler/
│   │   ├── crypto_scheduler.py     # unchanged — reference pattern
│   │   ├── repository.py           # unchanged
│   │   ├── stock_scheduler_repository.py  # NEW — Epic 6, mirrors scheduler_runs
│   │   └── supervisor.py           # NEW — Epic 6
│   ├── notifications/
│   │   ├── crypto_telegram_commands.py    # unified into commands.py (Epic 7)
│   │   └── commands.py             # NEW — Epic 7, replaces both command modules' role
│   ├── dashboard/
│   │   └── dashboard.py            # EDIT — service-layer reads (Epic 7)
│   └── paper_trading/
│       └── repository.py           # migrated data moves out in Epic 4; module kept until Epic 8 review
├── migrations/
│   └── 0001_portfolio_unify.py     # NEW — Epic 4 data migration, row-count parity verified
├── tests/
│   ├── conftest.py                 # NEW — Epic 2, DB isolation fixture
│   ├── test_alert.py               # unchanged (already correct; currently failing — fixed by Epic 1)
│   ├── test_schema_constraints.py  # NEW — Epic 2
│   ├── test_yahoo_provider.py      # NEW — Epic 3
│   ├── test_portfolio_service.py   # NEW — Epic 4
│   ├── test_portfolio_migration.py # NEW — Epic 4
│   ├── test_fee_config.py          # NEW — Epic 4
│   ├── test_alert_state.py         # NEW — Epic 5
│   ├── test_stock_scheduler_supervisor.py  # NEW — Epic 6
│   └── test_commands.py            # NEW — Epic 7
└── robotinaia.db                   # SQLite file, gitignored, backed up before every schema-touching step
```

---

## 4. Data Model

### Current (as-is, from `app/database/schema.py`, `app/scheduler/repository.py`,
`app/paper_trading/repository.py`)

```sql
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, score INTEGER NOT NULL, signal TEXT NOT NULL,
    price REAL NOT NULL, timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, quantity INTEGER NOT NULL, buy_price REAL NOT NULL,
    buy_date TEXT NOT NULL, target_price REAL, stop_loss REAL,
    status TEXT DEFAULT 'OPEN', sell_price REAL, sell_date TEXT,
    alerta_stop_enviada INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portfolio_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,   -- NO FK to portfolio.id today
    decision TEXT NOT NULL, precio REAL, timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stats ( ... );  -- unaffected by this blueprint

CREATE TABLE IF NOT EXISTS scheduler_runs (   -- declared in app/scheduler/repository.py, not schema.py
    id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL,
    hora_programada TEXT NOT NULL, ejecutado_en TEXT NOT NULL,
    UNIQUE(fecha, hora_programada)
);

CREATE TABLE IF NOT EXISTS paper_positions (   -- declared in app/paper_trading/repository.py
    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, direction TEXT NOT NULL,
    entry_price REAL NOT NULL, stop_price REAL NOT NULL, target_price REAL NOT NULL,
    size_usdt REAL NOT NULL, quantity REAL NOT NULL, opened_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN', close_price REAL, closed_at TEXT,
    close_reason TEXT, pnl_usdt REAL, pnl_pct REAL, scoring_id INTEGER
);
```

### Target (consolidated into `app/database/schema.py`, single source of truth)

```sql
PRAGMA user_version = 2;   -- bumped by app/database/migrations.py, tracked not hand-edited

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, score INTEGER NOT NULL,
    signal TEXT NOT NULL CHECK (signal IN ('PENDING','EXECUTED','SOLD','EXPIRED')),
    price REAL NOT NULL, timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,                       -- display symbol, provider-native (e.g. "BTC-USD" or "BTCUSDT")
    normalized_symbol TEXT NOT NULL,             -- canonical form, e.g. "BTC" — how stock and crypto positions dedupe
    asset_class TEXT NOT NULL CHECK (asset_class IN ('stock','crypto')),
    quantity REAL NOT NULL,
    buy_price REAL NOT NULL,
    buy_date TEXT NOT NULL,
    target_price REAL,
    stop_loss REAL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    sell_price REAL,
    sell_date TEXT,
    alerta_stop_enviada INTEGER NOT NULL DEFAULT 0,
    fee_pct_applied REAL,                        -- NULL until FeeConfig.configured=True is set for this asset_class
    fees_included INTEGER NOT NULL DEFAULT 0      -- boolean: was fee_pct_applied used in the stored P&L?
);

CREATE TABLE IF NOT EXISTS portfolio_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES portfolio(id),
    decision TEXT NOT NULL CHECK (decision IN ('MANTENER','VENDER')),
    precio REAL, timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL, hora_programada TEXT NOT NULL, ejecutado_en TEXT NOT NULL,
    UNIQUE(fecha, hora_programada)
);   -- crypto scheduler; consolidated here from app/scheduler/repository.py, same columns, no data change

CREATE TABLE IF NOT EXISTS stock_scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL, hora_programada TEXT NOT NULL, ejecutado_en TEXT NOT NULL,
    UNIQUE(fecha, hora_programada)
);   -- NEW, Epic 6 — same shape as scheduler_runs, separate table so stock/crypto windows never collide

CREATE TABLE IF NOT EXISTS alert_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES portfolio(id),
    alert_type TEXT NOT NULL CHECK (alert_type IN ('stop_loss','target')),
    status TEXT NOT NULL CHECK (status IN ('first_trigger','periodic_reminder','new_extreme','resolved')),
    trigger_price REAL NOT NULL,
    extreme_price REAL NOT NULL,          -- worst (stop) or best (target) price seen since first_trigger
    first_triggered_at TEXT NOT NULL,
    last_notified_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(position_id, alert_type)
);   -- NEW, Epic 5

-- paper_positions (app/paper_trading/repository.py) is NOT part of the consolidated schema going
-- forward: its rows are migrated INTO portfolio (asset_class='crypto') by migrations/0001, and the
-- module is retired once Epic 4's cutover completes (see §9.1 Coexistence plan).
```

**FK/CHECK additions applied via `PRAGMA foreign_keys=ON`** (set per-connection in
`app/database/connection.py`, since SQLite does not persist this pragma in the file — it must be
re-issued on every `sqlite3.connect()` call).

---

## 5. API Design

NOT APPLICABLE — RobotinaIA exposes no HTTP API. Its interfaces are: Telegram bot commands (see §6),
the Streamlit dashboard (read-only, internal), and the `MarketDataProvider` Python contract (§9,
Epic 3).

---

## 6. Frontend Architecture — Telegram command surface & dashboard

### Current (as-is)

- `telegram_commands.py`: `/portfolio`, `/buy`, `/sell`, `/vender`, `/mantener`, `/analisis` —
  stocks + legacy portfolio, imports `portfolio.py` directly. **Correction from an earlier draft of
  this section**: `/sell` and `/analisis` exist in the real `telegram_bot.py` today and were
  originally missing from this list, which would have made E7-T2's "zero `telegram_commands` imports"
  criterion impossible to satisfy without silently dropping those two commands. Confirmed with the
  operator: port everything (see Target below), and rename `/buy` to `/comprar`.
- `app/notifications/crypto_telegram_commands.py`: `/cripto` — crypto-only, read-only, calls
  `run_crypto_analysis(persistir=False)`.
- `app/dashboard/dashboard.py`: single Streamlit page, `st.metric` + `st.dataframe` over
  `SELECT * FROM signals`, raw SQL via `app/database/connection.get_connection()`.

### Target

- `app/notifications/commands.py`: one dispatch style (a `{command_name: handler}` map, matching the
  existing `python-telegram-bot` `CommandHandler` registration pattern already used in
  `telegram_bot.py`), covering `/portfolio`, `/comprar` (renamed from `/buy`), `/sell`, `/vender`,
  `/mantener`, `/analisis`, `/cripto` — all portfolio mutation through
  `app/services/portfolio_service.py`, never `portfolio.py` or raw SQL directly. `/sell` and
  `/analisis` are ported unchanged in shape (same signatures, `/sell` now calls
  `portfolio_service.sell_position` instead of `portfolio.sell_position`, `/analisis` untouched since
  it never touches portfolio state) — this is what makes "zero `telegram_commands` imports" achievable
  without removing functionality.
- `app/dashboard/dashboard.py` calls a small read-only query function exposed by
  `app/services/portfolio_service.py` (and the existing `app/database` signal-reading helpers)
  instead of composing SQL inline — same displayed metrics, same layout, same `st.dataframe` call.

No new pages, no new visual design — see §2.

---

## 7. Design System

NOT APPLICABLE — duplicate of §2 per template numbering; no design system work in this blueprint.

---

## 8. Authentication & Authorization

NOT APPLICABLE — single-operator system, no user accounts. The only "auth" surface is the Telegram
bot token (`TELEGRAM_BOT_TOKEN`) and chat id (`TELEGRAM_CHAT_ID`) used to restrict who the bot talks
to; that surface is exactly what Epic 1 (Security Blockers) hardens. No login flow, no roles, no
session model is introduced.

---

## 9. BUILD ORDER

**Numbering:** steps are numbered globally `01`–`25`, grouped into 8 epics per the required directory
layout. Every step carries: Type tag, Goal, Files touched (≤5), Acceptance criteria (EARS, ≤6),
Verify command(s), Depends on, Checkpoint tag. Every DB-schema-touching step's Checkpoint begins with
a real backup of `robotinaia.db` before the change and states the restore-from-backup rollback.

Legend: **[SECURITY BLOCKER]** · **[PRODUCTION-RISK FIX]** · **[ARCHITECTURAL MIGRATION]**

---

### Epic 1 — Security Blockers (`epics/01-security-blockers.md`)

#### Step 01 — Scrub `.env.example` and document credential rotation **[SECURITY BLOCKER]**

**Goal:** `.env.example` no longer carries a real token; the operator has explicit, copy-pasteable
instructions to rotate the leaked token and scrub git history. No code path depends on the exposed
token's specific value.

**Files touched:** `.env.example`

**Do (code, executed by the build agent):**
- Replace `TELEGRAM_BOT_TOKEN=8712940547:AAGT...` with
  `TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here`.
- Replace `TELEGRAM_CHAT_ID=1059706281` with `TELEGRAM_CHAT_ID=your-telegram-chat-id-here`.
- Leave `GEMINI_API_KEY=` as-is (already empty).

**Operator instructions (NOT executed by the build agent — real credentials, deliberate human action):**

1. Open Telegram, message `@BotFather`, run `/revoke` (or `/token`) for the RobotinaIA bot to issue a
   new token. This immediately invalidates `8712940547:AAGT...`.
2. Update the real `.env` (never committed) with the new token.
3. Scrub the leaked token from git history. Recommended: `git filter-repo` (not BFG — `filter-repo`
   is the currently maintained tool). Substitute the actual leaked token value (the one that was in
   `.env.example` before step 01 — check `git log -p -- .env.example` if you need to recover it) for
   `<LEAKED_TOKEN_VALUE>` below; it is deliberately not written out here so this file itself never
   carries the secret into git history:
   ```bash
   pip install git-filter-repo
   git filter-repo --replace-text <(echo '<LEAKED_TOKEN_VALUE>==>REDACTED')
   ```
   This rewrites history — coordinate with anyone else who has a clone, and force-push only after
   confirming the new history is correct locally. **The build agent must never run this command.**
4. Redeploy on Railway with the new token set in its environment variables.

**Acceptance criteria:**
1. **WHEN** `grep -c '8712940547' .env.example` runs **THE SYSTEM SHALL** exit with a count of 0.
2. **WHEN** `.env.example` is read **THE SYSTEM SHALL** show `TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here`
   and `TELEGRAM_CHAT_ID=your-telegram-chat-id-here` verbatim.
3. **WHEN** `app/core/settings.py` and every module reading `TELEGRAM_BOT_TOKEN` are inspected
   **THE SYSTEM SHALL** show they read it from `os.getenv`/`.env` only, never hardcode it — confirming
   no code path depends on the exposed value.

**Verify:**
```bash
grep -c '8712940547' .env.example; test $? -eq 1   # grep exits 1 = "no match found" = the leak is gone
grep -q 'your-telegram-bot-token-here' .env.example
! grep -rn '8712940547' --include=*.py .
```
*(`grep -c` on no match exits 1 with count "0" printed — `test $? -eq 1` asserts that exact "not
found" status; a real match would exit 0, which the assertion rejects.)*

**Depends on:** none — start here.

**Checkpoint:**
```bash
git add -A && git commit -m "step-01: scrub .env.example, document token rotation"
git tag step-01-security-env-scrub
```
No DB touched — no backup needed for this step.

**Operator verify (checkbox, not code-decidable):** operator confirms BotFather shows a newly issued
token, confirms Railway's environment variable was updated, and confirms (via `git log --oneline` on
the rewritten history, run manually, outside this build) that the old token string no longer appears
in any commit.

---

#### Step 02 — Add secret-pattern guard script **[SECURITY BLOCKER]**

**Goal:** a real-looking secret can never be committed again without a loud, local, pre-commit-style
failure.

**Files touched:** `scripts/check_no_secrets.py`, `tests/test_check_no_secrets.py`

**Do:** write `scripts/check_no_secrets.py` — a grep-based scanner over tracked and staged text files
for secret-shaped patterns: Telegram bot tokens (`\d{8,10}:[A-Za-z0-9_-]{35}`), generic API-key-shaped
strings (`(api|secret|token)[_-]?key\s*[:=]\s*['"][A-Za-z0-9_\-]{20,}['"]`), and anything assigned to
a real value in `.env.example` specifically (that file must only ever contain placeholders).
Exits 1 and prints the offending file:line if it finds a match; exits 0 otherwise. No network calls,
no third-party dependency — `re` + `subprocess` (`git diff --cached --name-only`) only, consistent
with "no new heavyweight dependencies."

**Acceptance criteria:**
1. **WHEN** `python scripts/check_no_secrets.py` runs against the current repo **THE SYSTEM SHALL**
   exit 0 (post step 01, nothing real-looking remains).
2. **WHEN** a Telegram-token-shaped string is staged in a temp fixture file **THE SYSTEM SHALL** cause
   the script to exit 1 and print the fixture's path.
3. **WHEN** `.env.example` contains only placeholder values **THE SYSTEM SHALL** be reported clean by
   the script.

**Verify:**
```bash
pytest tests/test_check_no_secrets.py
python scripts/check_no_secrets.py; test $? -eq 0
```

**Depends on:** 01.

**Checkpoint:**
```bash
git add -A && git commit -m "step-02: add secret-pattern guard script"
git tag step-02-secret-guard
```

---

### Epic 1 continued lives in `epics/01-security-blockers.md` (steps 01–02 only; the epic is
intentionally short — 2 steps — because this work is independent, fast, and mostly operator
instructions, per the required build order).

---

### Epic 2 — Database Integrity & Concurrency (`epics/02-database-integrity-and-concurrency.md`)

#### Step 03 — Fix `AlertEngine.UMBRAL_SENAL` **[PRODUCTION-RISK FIX]**

**Goal:** `AlertEngine.get_recommendation` stops throwing `AttributeError`; the already-failing
`tests/test_alert.py` passes.

**Rationale for the value (not a new business decision):** `tests/test_alert.py` requires
`get_recommendation(65) == "REVISAR"` and `get_recommendation(95) == "OPORTUNIDAD"`, and
`alert_engine.py`'s own logic already defines `>= 50` as `"REVISAR"`. `UMBRAL_SENAL` must therefore
satisfy `65 < UMBRAL_SENAL <= 95`. `80` is the value already implied by the codebase's convention of
round decade thresholds (`50` for `REVISAR`) and is the only value the existing tests were clearly
written around — it was never in dispute, the reference to it was simply left unimplemented.

**Files touched:** `app/core/settings.py`

**Do:** add `UMBRAL_SENAL = 80` to `Settings`, next to the other numeric thresholds, with the
docstring comment above explaining it satisfies the existing test contract (65→REVISAR, 95→OPORTUNIDAD).

**Acceptance criteria:**
1. **WHEN** `pytest tests/test_alert.py` runs **THE SYSTEM SHALL** exit 0 with 5 passed, 0 failed.
2. **WHEN** `AlertEngine().get_recommendation(80)` is called **THE SYSTEM SHALL** return `"OPORTUNIDAD"`.
3. **WHEN** `AlertEngine().get_recommendation(79)` is called **THE SYSTEM SHALL** return `"REVISAR"`.

**Verify:**
```bash
pytest tests/test_alert.py -v
```

**Depends on:** none (independent of Epic 1; can run in parallel).

**Checkpoint:**
```bash
git add -A && git commit -m "step-03: fix AlertEngine.UMBRAL_SENAL AttributeError"
git tag step-03-fix-umbral-senal
```
No DB touched.

---

#### Step 04 — Add `tests/conftest.py` DB-isolation fixture **[ARCHITECTURAL MIGRATION — test infra]**

**Goal:** every test that touches the database uses a temp SQLite file; no test can touch the real
`robotinaia.db`.

**Files touched:** `tests/conftest.py`

**Do:** add a `pytest` fixture `db_path(tmp_path, monkeypatch)` that creates an empty temp file,
monkeypatches `app.core.settings.Settings.DATABASE_NAME` to point at it (matching how
`app/database/connection.py` reads `Settings.DATABASE_NAME` on every `get_connection()` call — no
connection caching to fight), calls `app.database.schema.create_tables()` against it, and yields the
path. Autouse at function scope is deliberately **not** set — some existing tests
(`test_binance_provider.py`, pure unit tests) do not touch the DB and should not pay for a schema
build; tests that need it request `db_path` explicitly.

**Acceptance criteria:**
1. **WHEN** a test requests the `db_path` fixture and writes a row **THE SYSTEM SHALL** persist it
   only to the temp file, never to `robotinaia.db` (verified by mtime/hash of `robotinaia.db` being
   unchanged after the test run).
2. **WHEN** `pytest tests/` runs the full suite **THE SYSTEM SHALL** exit 0 with no test producing a
   `sqlite3.OperationalError` about a locked or missing table.
3. **WHEN** two tests both request `db_path` **THE SYSTEM SHALL** give each its own isolated file (no
   cross-test data leakage).

**Verify:**
```bash
sha1sum robotinaia.db > /tmp/before.sha1 2>/dev/null || echo "no-db-yet" > /tmp/before.sha1
pytest tests/ -q
sha1sum robotinaia.db > /tmp/after.sha1 2>/dev/null || echo "no-db-yet" > /tmp/after.sha1
diff /tmp/before.sha1 /tmp/after.sha1
```

**Depends on:** none (can land alongside step 05, per the required ordering — test infra lands early,
not deferred to the end).

**Checkpoint:**
```bash
git add -A && git commit -m "step-04: add tests/conftest.py DB isolation fixture"
git tag step-04-conftest-db-isolation
```

---

#### Step 05 — WAL mode + `busy_timeout` on every connection **[ARCHITECTURAL MIGRATION]**

**Goal:** SQLite runs in WAL mode with a busy timeout, eliminating the "database is locked" failure
mode across the three concurrent threads in `run_all.py`.

**Files touched:** `app/database/connection.py`, `tests/test_connection.py`

**Backup first (mandatory for every DB-schema-touching step):**
```bash
cp robotinaia.db "robotinaia.db.backup-step-05" 2>/dev/null || echo "no live DB yet, nothing to back up"
```

**Do:** in `get_connection()`, after `sqlite3.connect(Settings.DATABASE_NAME)`, execute
`PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA foreign_keys=ON` on every call — SQLite
does not persist `foreign_keys` across connections, and while `journal_mode=WAL` *is* persisted to the
file after the first call, issuing it every time is idempotent and removes any dependency on call
order across the three threads.

**Acceptance criteria:**
1. **WHEN** `get_connection()` is called **THE SYSTEM SHALL** return a connection with
   `PRAGMA journal_mode` reporting `wal`.
2. **WHEN** `get_connection()` is called **THE SYSTEM SHALL** return a connection with
   `PRAGMA busy_timeout` reporting `5000`.
3. **WHEN** two threads open connections concurrently and one holds a write transaction for 200ms
   **THE SYSTEM SHALL** have the second connection succeed (not raise `database is locked`) once the
   first commits, within the busy_timeout window.
4. **WHEN** `PRAGMA foreign_keys` is queried on a fresh connection **THE SYSTEM SHALL** report `1`.

**Verify:**
```bash
pytest tests/test_connection.py -v
sqlite3 robotinaia.db "PRAGMA journal_mode;"   # expect: wal
```

**Depends on:** 04.

**Checkpoint:**
```bash
git add -A && git commit -m "step-05: WAL mode, busy_timeout, foreign_keys pragma on every connection"
git tag step-05-wal-busy-timeout
```
**Rollback:** `cp robotinaia.db.backup-step-05 robotinaia.db` if WAL mode misbehaves on Railway's
volume (WAL uses extra `-wal`/`-shm` sidecar files — confirm Railway's persistent volume tolerates
this before considering the step done in production, noted in Risk Register §20).

---

#### Step 06 — Consolidate schema into `schema.py`, add FK/CHECK constraints, `user_version` tracking **[ARCHITECTURAL MIGRATION]**

**Goal:** every table definition lives in `app/database/schema.py`; FK and CHECK constraints are in
place; migrations are tracked via `PRAGMA user_version` instead of only additive
`_agregar_columna_si_no_existe`.

**Files touched:** `app/database/schema.py`, `app/database/migrations.py` (new),
`app/scheduler/repository.py`, `app/paper_trading/repository.py`

**Backup first:**
```bash
cp robotinaia.db "robotinaia.db.backup-step-06"
```

**Do:**
- Move `SCHEMA_SCHEDULER_RUNS` (currently in `app/scheduler/repository.py`) and
  `SCHEMA_PAPER_POSITIONS` (currently in `app/paper_trading/repository.py`) into `schema.py`'s
  `create_tables()`. Both modules keep their `crear_tabla()` functions as thin calls into the central
  schema for backward compatibility with any code that still calls them directly, but the
  authoritative `CREATE TABLE` text lives in one place.
- Add `stock_scheduler_runs` (§4) and `alert_state` (§4) table definitions — created here, wired up
  by Epics 5 and 6 respectively; defining the table now avoids a second schema-touching step later
  for something this cheap to add up front.
- Add `PRAGMA user_version` tracking: `app/database/migrations.py` exposes `current_version(conn)`
  and `apply_migrations(conn)`, which runs any migration whose number is greater than the DB's current
  `user_version` and then sets it. `create_tables()` calls `apply_migrations()` after the base
  `CREATE TABLE IF NOT EXISTS` statements, so idempotent runs (existing behavior) are preserved for
  fresh databases, and existing databases get FK/CHECK added via `ALTER TABLE` where SQLite supports
  it, or (for cases SQLite's limited `ALTER TABLE` cannot express, like adding a `CHECK` to an
  existing column) via the documented "rebuild the table" pattern: create `<table>_new` with the full
  target schema, `INSERT INTO ... SELECT`, drop old, rename.
- **Do not add FK/CHECK to `portfolio`'s new columns here** — `asset_class`/`normalized_symbol` are
  added in Epic 4 (step 10), which owns that migration; this step only adds constraints to columns
  that already exist today (`portfolio_decisions.position_id -> portfolio.id`,
  `signals.signal` CHECK, `portfolio.status` CHECK).

**Acceptance criteria:**
1. **WHEN** `sqlite3 robotinaia.db "PRAGMA foreign_key_check;"` runs after migration **THE SYSTEM
   SHALL** return no rows (no orphaned `portfolio_decisions.position_id`).
2. **WHEN** an `INSERT INTO portfolio_decisions (position_id, ...)` references a non-existent
   `portfolio.id` **THE SYSTEM SHALL** raise `sqlite3.IntegrityError`.
3. **WHEN** an `INSERT INTO signals (..., signal, ...)` uses a value outside
   `('PENDING','EXECUTED','SOLD','EXPIRED')` **THE SYSTEM SHALL** raise `sqlite3.IntegrityError`.
4. **WHEN** `create_tables()` runs twice in a row against the same DB **THE SYSTEM SHALL** be
   idempotent — no error, no duplicate constraint, `PRAGMA user_version` unchanged on the second run.
5. **WHEN** `sqlite3 robotinaia.db "PRAGMA user_version;"` runs **THE SYSTEM SHALL** report a value
   `>= 1`.

**Verify:**
```bash
pytest tests/test_schema_constraints.py -v
sqlite3 robotinaia.db "PRAGMA foreign_key_check;"
sqlite3 robotinaia.db "PRAGMA user_version;"
```

**Depends on:** 05.

**Checkpoint:**
```bash
git add -A && git commit -m "step-06: consolidate schema, add FK/CHECK constraints, user_version tracking"
git tag step-06-schema-consolidation
```
**Rollback:** `cp robotinaia.db.backup-step-06 robotinaia.db`.

---

#### Step 07 — Migration script: apply constraints to the live DB with row-count parity verify **[ARCHITECTURAL MIGRATION]**

**Goal:** the operator's actual `robotinaia.db` (not just fresh test databases) gets the new
constraints applied via the rebuild-table pattern, with a script that asserts identical row counts
before and after for every table.

**Files touched:** `migrations/0000_apply_constraints.py`, `tests/test_migration_row_counts.py`

**Backup first:**
```bash
cp robotinaia.db "robotinaia.db.backup-step-07"
```

**Do:** write `migrations/0000_apply_constraints.py` as a standalone runnable script: for each table
touched in step 06, count rows before, run `apply_migrations()`, count rows after, assert equality,
log via `loguru`, exit 1 on any mismatch (leaving the `.backup-step-07` file for manual restore).

**Acceptance criteria:**
1. **WHEN** `python migrations/0000_apply_constraints.py` runs against a copy of the live DB
   **THE SYSTEM SHALL** report identical row counts per table before and after, and exit 0.
2. **WHEN** the script is run against a DB with an orphaned `portfolio_decisions` row (test fixture)
   **THE SYSTEM SHALL** exit 1 and report which row violates the new FK, without silently dropping it.
3. **WHEN** `pytest tests/test_migration_row_counts.py` runs **THE SYSTEM SHALL** exit 0.

**Verify:**
```bash
cp robotinaia.db /tmp/robotinaia_migration_test.db 2>/dev/null || sqlite3 /tmp/robotinaia_migration_test.db "SELECT 1;"
DATABASE_PATH=/tmp/robotinaia_migration_test.db python migrations/0000_apply_constraints.py
pytest tests/test_migration_row_counts.py -v
```

**Depends on:** 06.

**Checkpoint:**
```bash
git add -A && git commit -m "step-07: migration script with row-count parity verification"
git tag step-07-migration-parity-verified
```
**Rollback:** `cp robotinaia.db.backup-step-07 robotinaia.db`.

---

### Epic 3 — Unified Market-Data Provider (`epics/03-unified-market-data-provider.md`)

#### Step 08 — `YahooProvider` implementing `MarketDataProvider` **[ARCHITECTURAL MIGRATION]**

**Goal:** stocks get the same retry/backoff/rate-limit resilience crypto already has.

**Files touched:** `app/providers/yahoo_provider.py`, `tests/test_yahoo_provider.py`

**Do:** implement `YahooProvider(MarketDataProvider)` in `app/providers/yahoo_provider.py`, mirroring
`BinanceProvider`'s shape: `MAX_REINTENTOS = 3`, exponential backoff on `requests`/`yfinance`
transient failures, treats `yfinance`'s empty-DataFrame response (Yahoo's way of signalling no data,
analogous to Binance's empty JSON body) as a raised `YahooProviderError`, matching
`BinanceProviderError`'s pattern. `get_stock(symbol)` wraps `yf.Ticker(symbol).history(period="1d",
interval="5m")` (same call already used ad hoc in `portfolio_alerts.py`) and returns the last close as
a `Stock`. Does not touch `yfinance`'s Yahoo-side rate limiting specifics beyond generic
retry-with-backoff, since Yahoo (unlike Binance) does not document stable 429-equivalent codes through
`yfinance` — the retry loop catches `Exception` broadly around the `yf.Ticker(...).history()` call,
consistent with `rsi2_connors.py`'s existing `except Exception: logger.exception(...)` pattern for the
same library.

**Acceptance criteria:**
1. **WHEN** `YahooProvider().get_stock("AAPL")` is called against a working network **THE SYSTEM
   SHALL** return a `Stock` with a positive `price`.
2. **WHEN** `yf.Ticker.history` is mocked to raise on the first 2 calls and succeed on the 3rd
   **THE SYSTEM SHALL** return successfully (retry worked), calling the mock exactly 3 times.
3. **WHEN** `yf.Ticker.history` is mocked to always raise **THE SYSTEM SHALL** raise
   `YahooProviderError` after exactly `MAX_REINTENTOS` attempts.
4. **WHEN** `yf.Ticker.history` returns an empty DataFrame **THE SYSTEM SHALL** raise
   `YahooProviderError`, not crash on an empty-frame index error.

**Verify:**
```bash
pytest tests/test_yahoo_provider.py -v
```

**Depends on:** none (independent of DB work; may run in parallel with Epic 2, per required
ordering).

**Checkpoint:**
```bash
git add -A && git commit -m "step-08: add YahooProvider with retry/backoff, mirrors BinanceProvider"
git tag step-08-yahoo-provider
```

---

#### Step 09 — Wire `rsi2_connors.py` to `YahooProvider` **[ARCHITECTURAL MIGRATION]**

**Goal:** the RSI(2)-Connors strategy's daily-data fetch goes through `YahooProvider` instead of
calling `yfinance` directly, with zero change to the entry/exit signal logic.

**Files touched:** `app/strategies/rsi2_connors.py`, `tests/test_rsi2_connors_provider.py`

**Do:** replace `_cargar_datos_diarios`'s direct `yf.Ticker(symbol).history(period=PERIODO_DESCARGA,
interval="1d")` call with a `YahooProvider`-based equivalent. `YahooProvider.get_stock()` only returns
a single latest price (matching `MarketDataProvider`'s ABC contract), which is not enough for
`rsi2_connors.py`'s 2-year daily history requirement — add a `get_daily_history(symbol, period)`
method to `YahooProvider` (not part of the ABC, same pattern `BinanceProvider` uses for its
crypto-specific methods like `get_ohlcv` that live outside `MarketDataProvider`'s minimal contract),
apply the same retry/backoff wrapper to it, and call that from `_cargar_datos_diarios`. Every
downstream function (`_limpiar_datos`, `_calcular_indicadores`, `_hubo_cruce_entrada_hoy`,
`_hubo_condicion_salida_hoy`) is untouched — same DataFrame shape in, same signal logic.

**Acceptance criteria:**
1. **WHEN** `_cargar_datos_diarios("AAPL")` is called **THE SYSTEM SHALL** return the same DataFrame
   shape (columns `Open/High/Low/Close/Volume`, DatetimeIndex) it returned before this change,
   verified against a recorded fixture.
2. **WHEN** the underlying data source fails transiently **THE SYSTEM SHALL** retry via
   `YahooProvider`'s backoff instead of failing on the first attempt (mocked test).
3. **WHEN** `ejecutar_rsi2_connors()` runs against a fixture where one symbol's fetch fails
   permanently **THE SYSTEM SHALL** log and continue to the next symbol (existing per-symbol
   try/except in `ejecutar_rsi2_connors` preserved, unchanged).
4. **WHEN** `pytest tests/test_score.py` (existing scoring/signal tests, if any exercise this path) is
   re-run **THE SYSTEM SHALL** still pass — confirming no behavior change to the signal math.

**Verify:**
```bash
pytest tests/test_rsi2_connors_provider.py -v
pytest tests/test_score.py -v
```

**Depends on:** 08.

**Checkpoint:**
```bash
git add -A && git commit -m "step-09: wire rsi2_connors.py to YahooProvider, no signal-logic change"
git tag step-09-rsi2-yahoo-provider-wired
```

---

### Epic 4 — Unified Portfolio & P&L (`epics/04-unified-portfolio-and-pnl.md`)

#### Step 10 — Schema delta: `asset_class`, `normalized_symbol`, fee columns on `portfolio` **[ARCHITECTURAL MIGRATION]**

**Goal:** `portfolio` can represent both stock and crypto positions with a stable dedup key.

**Files touched:** `app/database/schema.py`, `app/database/migrations.py`, `tests/test_schema_constraints.py`

**Backup first:**
```bash
cp robotinaia.db "robotinaia.db.backup-step-10"
```

**Do:** extend `SCHEMA_PORTFOLIO` (§4) with `normalized_symbol`, `asset_class` (CHECK
`IN ('stock','crypto')`), `fee_pct_applied`, `fees_included`. Add a migration in
`app/database/migrations.py` (version bump) that, for every existing row: sets `asset_class='stock'`
unless the symbol is one of `Settings.ACTIVOS_CRIPTO` (Yahoo-style `BTC-USD` etc.), in which case
`'crypto'`; sets `normalized_symbol` by stripping the provider-specific suffix
(`BTC-USD` → `BTC`, `BTCUSDT` → `BTC`) via a small mapping table
`{"BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL"}` (reverse-usable for `BTCUSDT` → `BTC` etc.
once step 13 migrates `paper_positions` rows in); for stock rows, `normalized_symbol = symbol`
unchanged (no BVC/international suffix collision risk today). Sets `fees_included=0`,
`fee_pct_applied=NULL` for all existing rows (fee-not-configured is the honest state until Epic 4
step 11 ships `FeeConfig`).

**Acceptance criteria:**
1. **WHEN** the migration runs against a DB containing the current `BTC-USD` id=2 row **THE SYSTEM
   SHALL** set `asset_class='crypto'`, `normalized_symbol='BTC'` on that row.
2. **WHEN** the migration runs against existing stock rows **THE SYSTEM SHALL** set
   `asset_class='stock'`, `normalized_symbol` equal to the existing `symbol`.
3. **WHEN** an `INSERT INTO portfolio` supplies `asset_class='option'` (invalid) **THE SYSTEM SHALL**
   raise `sqlite3.IntegrityError`.
4. **WHEN** the migration runs twice **THE SYSTEM SHALL** be idempotent (second run is a no-op,
   `user_version` unchanged after the first successful bump).

**Verify:**
```bash
pytest tests/test_schema_constraints.py -k portfolio_asset_class -v
sqlite3 robotinaia.db "SELECT symbol, asset_class, normalized_symbol FROM portfolio;"
```

**Depends on:** 07.

**Checkpoint:**
```bash
git add -A && git commit -m "step-10: add asset_class/normalized_symbol/fee columns to portfolio"
git tag step-10-portfolio-schema-delta
```
**Rollback:** `cp robotinaia.db.backup-step-10 robotinaia.db`.

---

#### Step 11 — `FeeConfig` strategy interface **[ARCHITECTURAL MIGRATION]**

**Goal:** an extensible per-asset-class fee interface exists, defaulting to
`fee_pct=0, configured=False`, so every P&L output can honestly flag whether fees were counted.

**Files touched:** `app/services/fee_config.py`, `tests/test_fee_config.py`

**Do:** `app/services/fee_config.py` defines `FeeConfig(ABC)` with `apply(gross_pnl, quantity,
price) -> tuple[float, bool]` (returns adjusted P&L and whether it was fee-adjusted), and a default
`FlatPercentageFeeConfig(fee_pct=0.0, configured=False)` implementation per asset class
(`STOCK_FEE_CONFIG`, `CRYPTO_FEE_CONFIG`, both defaulting unconfigured). No real fee numbers are
invented — see Non-Goals §1.

**Acceptance criteria:**
1. **WHEN** `STOCK_FEE_CONFIG.apply(100.0, 10, 50.0)` is called with defaults **THE SYSTEM SHALL**
   return `(100.0, False)` — P&L unchanged, `configured` flag `False`.
2. **WHEN** a `FlatPercentageFeeConfig(fee_pct=0.1, configured=True)` is applied to a `100.0` gross
   P&L **THE SYSTEM SHALL** return a value less than `100.0` and `configured=True`.
3. **WHEN** `fee_pct` is negative **THE SYSTEM SHALL** raise `ValueError` at construction.

**Verify:**
```bash
pytest tests/test_fee_config.py -v
```

**Depends on:** none (pure Python, no DB — can run in parallel with step 10).

**Checkpoint:**
```bash
git add -A && git commit -m "step-11: add FeeConfig strategy interface, defaults unconfigured"
git tag step-11-fee-config
```

---

#### Step 12 — `app/services/portfolio_service.py`: unified buy/sell/trailing-stop/P&L **[ARCHITECTURAL MIGRATION]**

**Goal:** one service owns portfolio mutation and P&L for both asset classes, fee-aware, with the
biggest test-coverage gap (trailing-stop logic) finally covered.

**Files touched:** `app/services/portfolio_service.py`, `tests/test_portfolio_service.py`

**Do:** port `portfolio.py`'s `add_position`, `get_open_positions`, `sell_position`,
`actualizar_trailing_stop`, `marcar_alerta_stop`, `registrar_decision` into
`app/services/portfolio_service.py` as functions taking an explicit `asset_class` parameter and
writing `normalized_symbol` on insert (via the same mapping used in step 10's migration, extracted
into a shared `app/services/symbol_normalization.py` helper so the migration and the service use one
definition, not two). `sell_position` now runs its P&L through the asset class's `FeeConfig.apply(...)`
and stores `fee_pct_applied`/`fees_included` on the row. Logic (trailing-stop math, stop-loss
comparison) is a direct, tested port of the existing behavior in `portfolio.py` and
`portfolio_alerts.py._revisar_trailing_stop` — no new business rules.

**Acceptance criteria:**
1. **WHEN** `add_position("BTC-USD", 0.01, 50000, asset_class="crypto")` is called **THE SYSTEM
   SHALL** insert a row with `normalized_symbol='BTC'`.
2. **WHEN** `sell_position` is called on a position under the default unconfigured `FeeConfig`
   **THE SYSTEM SHALL** compute P&L identically to the pre-migration `(sell_price - buy_price) *
   quantity` formula and set `fees_included=0`.
3. **WHEN** price crosses the `target_price` in a simulated trailing-stop cycle **THE SYSTEM SHALL**
   raise `stop_loss` to the old `target_price` and raise `target_price` by exactly `TRAILING_STEP_PCT`
   (3%), matching `portfolio_alerts.py`'s existing constant.
4. **WHEN** trailing-stop is applied twice in sequence (two consecutive target hits) **THE SYSTEM
   SHALL** compound correctly — second stop equals first target, second target is 3% above that.
5. **WHEN** `sell_position` is called with a configured `FeeConfig(fee_pct=0.001, configured=True)`
   **THE SYSTEM SHALL** report `fees_included=1` and a P&L strictly less than the fee-unaware
   calculation for a profitable trade.

**Verify:**
```bash
pytest tests/test_portfolio_service.py -v
```

**Depends on:** 10, 11.

**Checkpoint:**
```bash
git add -A && git commit -m "step-12: add portfolio_service.py, unified buy/sell/trailing-stop/P&L, fee-aware"
git tag step-12-portfolio-service
```

---

#### Step 13 — Migration script: `portfolio` + `paper_positions` → unified schema, row-count parity **[ARCHITECTURAL MIGRATION]**

**Goal:** existing `portfolio` and `paper_positions` rows move into the unified schema with no data
loss, verified by row-count parity.

**Files touched:** `migrations/0001_portfolio_unify.py`, `tests/test_portfolio_migration.py`

**Backup first:**
```bash
cp robotinaia.db "robotinaia.db.backup-step-13"
```

**Do:** `migrations/0001_portfolio_unify.py`: counts rows in `portfolio` and `paper_positions` before;
for each `paper_positions` row, inserts an equivalent `portfolio` row
(`asset_class='crypto'`, `normalized_symbol` from the `BTCUSDT`→`BTC` mapping,
`symbol=paper_positions.symbol`, `status` mapped `OPEN`→`OPEN`/anything else→`CLOSED`,
`sell_price=close_price`, `sell_date=closed_at`); leaves `paper_positions` table intact (not dropped —
see §9.1 Coexistence plan) but marks migrated rows via a new `migrated_to_portfolio_id` column added
to `paper_positions` for traceability; asserts
`count(portfolio after) == count(portfolio before) + count(paper_positions before)`; exits 1 on any
mismatch.

**Acceptance criteria:**
1. **WHEN** the migration runs against a copy of the live DB **THE SYSTEM SHALL** report
   `portfolio` row count after equal to `portfolio` before plus `paper_positions` before, and exit 0.
2. **WHEN** the migration runs against a fixture with 3 `paper_positions` rows and 2 `portfolio` rows
   **THE SYSTEM SHALL** produce exactly 5 `portfolio` rows after.
3. **WHEN** a `paper_positions` row has an unrecognized symbol (not in the BTC/ETH/SOL mapping)
   **THE SYSTEM SHALL** log a warning, skip that row, and report it in the final summary rather than
   silently dropping it or crashing the whole migration.
4. **WHEN** the migration is run a second time **THE SYSTEM SHALL** detect already-migrated rows via
   `migrated_to_portfolio_id IS NOT NULL` and skip them (idempotent, no duplicate inserts).

**Verify:**
```bash
cp robotinaia.db /tmp/migration_test.db
DATABASE_PATH=/tmp/migration_test.db python migrations/0001_portfolio_unify.py
pytest tests/test_portfolio_migration.py -v
```

**Depends on:** 12.

**Checkpoint:**
```bash
git add -A && git commit -m "step-13: migrate portfolio + paper_positions into unified schema, parity verified"
git tag step-13-portfolio-migration
```
**Rollback:** `cp robotinaia.db.backup-step-13 robotinaia.db`.

---

#### Step 14 — Resolve the stale `BTC-USD` position (operator decision) **[PRODUCTION-RISK FIX]**

**Goal:** the stuck `BTC-USD` id=2 `OPEN` position stops silently sitting unmanaged; the operator
makes an explicit, documented choice.

**Files touched:** `migrations/0002_resolve_stale_btc.py` (both paths implemented, gated by a CLI
flag), `tests/test_resolve_stale_btc.py`

**Backup first:**
```bash
cp robotinaia.db "robotinaia.db.backup-step-14"
```

**Do:** write `migrations/0002_resolve_stale_btc.py` with two modes, selected by an explicit
`--action=close|migrate` flag (no default — running without a flag prints both options and exits 2,
forcing a deliberate choice):
- `--action=migrate`: leaves the position `OPEN`, fully migrated into the unified `portfolio_service`
  model with its current `stop_loss`/`target_price`/`buy_price` intact, now managed by Epic 5's alert
  state machine going forward.
- `--action=close`: fetches the current `BTC-USD` price via `YahooProvider` (from Epic 3, already
  shipped), and calls `portfolio_service.sell_position(2, current_price)`, closing it at market — this
  path requires the operator to explicitly pass `--confirm-close` in addition to `--action=close`, a
  second flag, so an accidental single-flag invocation cannot close a real position.

**This step's acceptance criterion is deliberately about the tooling being correct and safe, not
about which path the operator picks** — closing a real financial position is the operator's call
(per the brief), never code's.

**Acceptance criteria:**
1. **WHEN** `python migrations/0002_resolve_stale_btc.py` runs with no flags **THE SYSTEM SHALL**
   print both options and exit 2, taking no DB action.
2. **WHEN** run with `--action=migrate` **THE SYSTEM SHALL** leave the position status `OPEN` and set
   its `asset_class`/`normalized_symbol` per Epic 4's schema, verified by a subsequent
   `portfolio_service.get_open_positions()` call including it.
3. **WHEN** run with `--action=close` but without `--confirm-close` **THE SYSTEM SHALL** exit 2 and
   take no DB action (the safety-flag guard).
4. **WHEN** run with `--action=close --confirm-close` against a test fixture **THE SYSTEM SHALL** set
   the position's `status='CLOSED'` with a `sell_price` from `YahooProvider` and a non-null
   `sell_date`.

**Verify:**
```bash
python migrations/0002_resolve_stale_btc.py; test $? -eq 2
pytest tests/test_resolve_stale_btc.py -v
```

**Depends on:** 13, 09 (needs `YahooProvider` for the close path's live price — cross-epic dependency,
declared explicitly here since `YahooProvider` only handles Yahoo-listed symbols and `BTC-USD` is
Yahoo-style, matching the existing `portfolio_alerts.py` behavior for this same position today).

**Checkpoint:**
```bash
git add -A && git commit -m "step-14: tooling to resolve stale BTC-USD position (operator chooses close/migrate)"
git tag step-14-stale-btc-tooling
```
**Rollback:** `cp robotinaia.db.backup-step-14 robotinaia.db`.

**Operator action required before this step is considered fully applied in production:** run the
script with the chosen `--action` flag against the real `robotinaia.db`. This is a real financial
decision — the blueprint ships the tool, not the decision.

---

#### Step 15 — Parity harness: old vs. new P&L on historical rows **[ARCHITECTURAL MIGRATION]**

**Goal:** a script proves the new `portfolio_service` P&L math matches the old `portfolio.py` math
exactly for every historical closed position (fee-unconfigured case), giving real evidence for the
cutover decision in §9.1.

**Files touched:** `scripts/parity_harness_portfolio.py`, `tests/test_parity_harness.py`

**Do:** `scripts/parity_harness_portfolio.py` reads every `CLOSED` row migrated by step 13, recomputes
P&L both via the old formula (`(sell_price - buy_price) * quantity`, inlined, since `portfolio.py`
itself is still present until Epic 8) and via `portfolio_service`'s fee-aware path with the default
unconfigured `FeeConfig` (which must produce byte-identical numbers to the old formula, since
`fee_pct=0`), asserts equality per row, prints a summary, exits 1 on any mismatch.

**Acceptance criteria:**
1. **WHEN** the harness runs against the migrated DB **THE SYSTEM SHALL** report 0 mismatches across
   every `CLOSED` position and exit 0.
2. **WHEN** a mismatch is deliberately injected in a test fixture (one row's stored P&L manually
   corrupted) **THE SYSTEM SHALL** detect it, print the row id and both values, and exit 1.

**Verify:**
```bash
python scripts/parity_harness_portfolio.py
pytest tests/test_parity_harness.py -v
```

**Depends on:** 13.

**Checkpoint:**
```bash
git add -A && git commit -m "step-15: add old-vs-new P&L parity harness"
git tag step-15-parity-harness
```

---

### Epic 5 — Alert Reliability (`epics/05-alert-reliability.md`)

#### Step 16 — `alert_state` persistence + state machine **[ARCHITECTURAL MIGRATION]**

**Goal:** stop-loss/target alert state survives process restart with explicit transitions.

**Files touched:** `app/alerts/alert_state.py`, `tests/test_alert_state.py`

**Do:** `app/alerts/alert_state.py` implements the state machine against the `alert_state` table
(schema already added in step 06): `record_trigger(position_id, alert_type, price)` — inserts
`first_trigger` if no row exists for `(position_id, alert_type)`, else compares `price` against the
stored `extreme_price` per `alert_type` (stop: track the lowest price seen; target: track the
highest) and against a configurable `Settings.ALERTA_CAMBIO_MATERIAL_PCT` (default `0.5`) to decide
`new_extreme` vs. no-op; `should_notify(position_id, alert_type, now)` returns `True` if status is
`first_trigger`/`new_extreme` (always notify) or if `now - last_notified_at >=
Settings.ALERTA_RECORDATORIO_HORAS` (default `6`) hours and status is not `resolved`;
`resolve(position_id, alert_type)` — called when price recovers past the trigger level, matching
today's `marcar_alerta_stop(position_id, False)` re-arm behavior.

**Acceptance criteria:**
1. **WHEN** `record_trigger` is called for a position/alert_type with no existing row **THE SYSTEM
   SHALL** insert `status='first_trigger'` and `should_notify` **THE SYSTEM SHALL** return `True`.
2. **WHEN** `record_trigger` is called again within 6 hours at a price within 0.5% of the stored
   extreme **THE SYSTEM SHALL** leave status unchanged and `should_notify` **THE SYSTEM SHALL** return
   `False` (duplicate suppression).
3. **WHEN** `record_trigger` is called with a price worse than the stored extreme by more than 0.5%
   **THE SYSTEM SHALL** set `status='new_extreme'`, update `extreme_price`, and `should_notify`
   **THE SYSTEM SHALL** return `True`.
4. **WHEN** more than 6 hours have elapsed since `last_notified_at` with no new extreme **THE SYSTEM
   SHALL** set `status='periodic_reminder'` and `should_notify` **THE SYSTEM SHALL** return `True`.
5. **WHEN** `resolve` is called **THE SYSTEM SHALL** set `status='resolved'`, `resolved_at` non-null,
   and a subsequent `record_trigger` on the same `(position_id, alert_type)` **THE SYSTEM SHALL**
   start a fresh `first_trigger` cycle.

**Verify:**
```bash
pytest tests/test_alert_state.py -v
```

**Depends on:** 12 (reads/writes rows keyed to `portfolio.id` via `portfolio_service`).

**Checkpoint:**
```bash
git add -A && git commit -m "step-16: add persisted alert state machine"
git tag step-16-alert-state-machine
```

---

#### Step 17 — Wire `portfolio_alerts.py` to the alert state machine **[ARCHITECTURAL MIGRATION]**

**Goal:** the stuck-position failure mode (stop-loss alert fires once, never again) is closed for
every future position, not retroactively guaranteed for the one already resolved in step 14.

**Files touched:** `app/alerts/portfolio_alerts.py`, `tests/test_portfolio_alerts_state.py`

**Do:** replace `_revisar_stop_loss`'s `marcar_alerta_stop` bool flag with calls to
`alert_state.record_trigger` / `should_notify` / `resolve`; same replacement for the trailing-stop
target-hit path (`_revisar_trailing_stop` already re-notifies every hit today via its `while` loop —
add `record_trigger(alert_type="target")` there too, for consistency and future extensibility, but do
not change its existing every-hit notify behavior, since that one is not broken). `portfolio.py`'s
`marcar_alerta_stop`/`alerta_stop_enviada` column stay as dead weight on the legacy path until Epic 8
removes `portfolio.py`; the new path in `portfolio_alerts.py` no longer reads or writes them.

**Acceptance criteria:**
1. **WHEN** a position's price stays below `stop_loss` for two consecutive scheduler cycles more than
   6 hours apart with no material price change **THE SYSTEM SHALL** send exactly 2 Telegram
   notifications (`first_trigger` then `periodic_reminder`), not 0 (today's bug) and not one per
   cycle.
2. **WHEN** price moves to a new low below the stop by more than 0.5% between cycles **THE SYSTEM
   SHALL** send an immediate `new_extreme` notification regardless of the 6-hour window.
3. **WHEN** price recovers above `stop_loss` **THE SYSTEM SHALL** call `resolve` and a subsequent
   breach **THE SYSTEM SHALL** notify immediately (fresh `first_trigger`).

**Verify:**
```bash
pytest tests/test_portfolio_alerts_state.py -v
```

**Depends on:** 16.

**Checkpoint:**
```bash
git add -A && git commit -m "step-17: wire portfolio_alerts.py to persisted alert state machine"
git tag step-17-portfolio-alerts-state-wired
```

---

### Epic 6 — Scheduler Resilience (`epics/06-scheduler-resilience.md`)

#### Step 18 — Stock scheduler idempotency table **[ARCHITECTURAL MIGRATION]**

**Goal:** the stock scheduler gets the same duplicate-run protection the crypto scheduler already
has, via `stock_scheduler_runs` (schema added in step 06).

**Files touched:** `app/scheduler/stock_scheduler_repository.py`, `tests/test_stock_scheduler_repository.py`

**Do:** port `app/scheduler/repository.py`'s `intentar_registrar_ejecucion` shape 1:1 into
`app/scheduler/stock_scheduler_repository.py` against `stock_scheduler_runs`, keyed the same way
(`fecha`, `hora_programada`).

**Acceptance criteria:**
1. **WHEN** `intentar_registrar_ejecucion("2026-08-15", "09:00")` is called twice **THE SYSTEM SHALL**
   return `True` the first time and `False` the second.
2. **WHEN** called for two different `hora_programada` values on the same `fecha` **THE SYSTEM SHALL**
   return `True` for both (no cross-window collision).

**Verify:**
```bash
pytest tests/test_stock_scheduler_repository.py -v
```

**Depends on:** 06 (table exists).

**Checkpoint:**
```bash
git add -A && git commit -m "step-18: add stock scheduler idempotency table"
git tag step-18-stock-scheduler-idempotency
```

---

#### Step 19 — Supervised stock-scheduler thread with capped restart + escalation **[ARCHITECTURAL MIGRATION]**

**Goal:** an unhandled exception in the stock scheduler no longer means the service silently stops
covering stocks forever while looking healthy.

**Files touched:** `app/scheduler/supervisor.py`, `run_all.py`, `tests/test_stock_scheduler_supervisor.py`

**Do:** `app/scheduler/supervisor.py` implements `run_supervised(target, name, max_restarts=5,
backoff_base_seconds=30)`: runs `target()` in a loop; on unhandled exception, logs via `loguru`,
sleeps `backoff_base_seconds * (2 ** restart_count)` (capped, e.g. at 30 min), increments a restart
counter, and restarts — until `max_restarts` is hit, at which point it sends one Telegram alert via
`enviar_mensaje_telegram` ("stock scheduler failed N times, giving up — manual intervention needed")
and stops retrying (never restarts forever silently, per the requirement). `run_all.py`'s
`_iniciar_scheduler` is rewritten to call `run_supervised(scheduler_module.main, "stock_scheduler")`
instead of its current single bare try/except.

**Acceptance criteria:**
1. **WHEN** `target()` raises on its first 2 calls and succeeds on the 3rd **THE SYSTEM SHALL** call
   it exactly 3 times, with increasing sleep between attempts, and never send the escalation alert.
2. **WHEN** `target()` always raises **THE SYSTEM SHALL** call it exactly `max_restarts` times, then
   send exactly one Telegram escalation message and stop calling `target()` again.
3. **WHEN** the escalation fires **THE SYSTEM SHALL** include the exception type/message and the
   restart count in the Telegram message.
4. **WHEN** `run_all.py` starts **THE SYSTEM SHALL** launch the stock scheduler through
   `run_supervised`, verified by inspecting the thread target function reference.

**Verify:**
```bash
pytest tests/test_stock_scheduler_supervisor.py -v
```

**Depends on:** 18.

**Checkpoint:**
```bash
git add -A && git commit -m "step-19: supervise stock scheduler thread, capped restart + Telegram escalation"
git tag step-19-stock-scheduler-supervised
```

---

### Epic 7 — Telegram/Dashboard Consolidation (`epics/07-telegram-dashboard-consolidation.md`)

#### Step 20 — `app/notifications/commands.py`: one command-handling style **[ARCHITECTURAL MIGRATION]**

**Goal:** stock and crypto commands share one dispatch style, both backed by `portfolio_service.py`.

**Files touched:** `app/notifications/commands.py`, `tests/test_commands.py`

**Do:** `app/notifications/commands.py` exposes `portfolio_command()`, `comprar_command(...)`
(renamed from `buy_command`), `sell_command(...)`, `vender_command(...)`, `mantener_command(...)`
(ported from `telegram_commands.py`, rewritten against `portfolio_service` instead of `portfolio.py`),
`analisis_command(...)` (ported unchanged — never touches portfolio state), and `cripto_command()`
(moved as-is from `app/notifications/crypto_telegram_commands.py`, unchanged body — it already does
not touch the portfolio). All seven are collected in one `COMMANDS: dict[str, Callable]` map for
registration in `telegram_bot.py`. `sell_command` and `analisis_command` were not in this task's
original scope but are required for E7-T2's "zero `telegram_commands` imports" criterion to hold
without silently dropping `/sell` and `/analisis` — confirmed with the operator.

**Acceptance criteria:**
1. **WHEN** `portfolio_command()` is called with open positions in both asset classes **THE SYSTEM
   SHALL** list both stock and crypto positions in one output (proving the unification — today's
   `telegram_commands.py` version cannot see crypto positions at all).
2. **WHEN** `comprar_command` is called **THE SYSTEM SHALL** create a position via
   `portfolio_service.add_position`, not `portfolio.add_position`.
3. **WHEN** `cripto_command()` is called **THE SYSTEM SHALL** return output identical in shape to the
   current `app/notifications/crypto_telegram_commands.py` implementation (same fields, same
   read-only `persistir=False` behavior).

**Verify:**
```bash
pytest tests/test_commands.py -v
```

**Depends on:** 12.

**Checkpoint:**
```bash
git add -A && git commit -m "step-20: add unified app/notifications/commands.py"
git tag step-20-unified-commands
```

---

#### Step 21 — Cutover: `telegram_bot.py` registers unified commands **[ARCHITECTURAL MIGRATION]**

**Goal:** the bot actually uses the new command module; old handlers stop being registered (coexist
briefly per §9.1, then the old modules are inert until Epic 8 deletes them).

**Files touched:** `telegram_bot.py`, `tests/test_telegram_bot_registration.py`

**Do:** update `telegram_bot.py`'s `CommandHandler` registrations to point at
`app/notifications/commands.py`'s functions instead of `telegram_commands.py`'s. `telegram_commands.py`
itself is left in place, unregistered and unused by any live code path — this is the coexistence
window from §9.1: it still exists on disk (so Epic 8 can diff against it if needed) but nothing
imports it after this step.

**Acceptance criteria:**
1. **WHEN** `telegram_bot.py` is inspected **THE SYSTEM SHALL** show zero `import` statements
   referencing `telegram_commands` or `app.notifications.crypto_telegram_commands`.
2. **WHEN** the bot's registered command handlers are enumerated **THE SYSTEM SHALL** show
   `/portfolio`, `/comprar`, `/vender`, `/mantener`, `/cripto` all pointing at
   `app.notifications.commands` functions.
3. **WHEN** `pytest tests/` runs the full suite **THE SYSTEM SHALL** exit 0 (no import errors from the
   rewiring).

**Verify:**
```bash
pytest tests/test_telegram_bot_registration.py -v
pytest tests/ -q
```

**Depends on:** 20.

**Checkpoint:**
```bash
git add -A && git commit -m "step-21: cut over telegram_bot.py to unified commands module"
git tag step-21-telegram-bot-cutover
```

---

#### Step 22 — Route dashboard through the service layer **[ARCHITECTURAL MIGRATION]**

**Goal:** the Streamlit dashboard stops running raw SQL and calls a service function instead, so it
does not silently break on future schema changes.

**Files touched:** `app/dashboard/dashboard.py`, `app/services/signal_query_service.py` (new),
`tests/test_signal_query_service.py`

**Do:** extract `dashboard.py`'s `cargar_senales()` query into
`app/services/signal_query_service.py::listar_senales() -> pd.DataFrame`, same SQL, same columns.
`dashboard.py` imports and calls it instead of composing SQL inline. Zero layout, metric, or visual
change — same three `st.metric` columns, same `st.dataframe`.

**Acceptance criteria:**
1. **WHEN** `listar_senales()` is called against a fixture DB with 3 signals **THE SYSTEM SHALL**
   return a `DataFrame` with exactly 3 rows and columns `id, symbol, score, signal, price, timestamp`.
2. **WHEN** `dashboard.py`'s source is inspected **THE SYSTEM SHALL** show zero inline `SELECT`
   statements (all reads go through `signal_query_service`).
3. **WHEN** the dashboard boots against an empty DB **THE SYSTEM SHALL** render the "No existen
   señales todavía." warning path unchanged (same string, same behavior).

**Verify:**
```bash
pytest tests/test_signal_query_service.py -v
! grep -q "SELECT" app/dashboard/dashboard.py
```

**Depends on:** none beyond existing schema (independent of Epic 4/6, can run any time after Epic 2).

**Checkpoint:**
```bash
git add -A && git commit -m "step-22: route dashboard through signal_query_service"
git tag step-22-dashboard-service-layer
```

---

### Epic 8 — Legacy Decommission (`epics/08-legacy-decommission.md`)

#### Step 23 — Delete confirmed dead code **[ARCHITECTURAL MIGRATION — decommission]**

**Goal:** `scoring.py`, `stats.py`, `bollinger.py` (root) are removed, re-confirming they are still
unreferenced at execution time (they were already confirmed dead in the brownfield audit; this step
re-checks before deleting, since code may have changed since the audit).

**Files touched:** `scoring.py` (delete), `stats.py` (delete), `bollinger.py` (delete)

**Do:** re-run the same check the audit used
(`grep -rln "import scoring\|from scoring\|import stats\|from stats\|import bollinger\|from bollinger"
main.py run_all.py app/ tests/`) — if it returns nothing, delete the three files. If it returns a hit,
stop and report (do not delete); this would mean the codebase changed since the audit and the
blueprint's premise for this step no longer holds.

**Acceptance criteria:**
1. **WHEN** the reference-check grep runs before deletion **THE SYSTEM SHALL** return zero matches.
2. **WHEN** `pytest tests/` runs after deletion **THE SYSTEM SHALL** exit 0 (nothing depended on
   them).
3. **WHEN** `python -c "import main; import run_all"` runs after deletion **THE SYSTEM SHALL** exit 0
   (no broken imports).

**Verify:**
```bash
! grep -rln "import scoring\|from scoring\|import stats\|from stats\|import bollinger\|from bollinger" main.py run_all.py app/ tests/
pytest tests/ -q
```

**Depends on:** none (independent leaf; can run any time, placed last per the required ordering to
keep decommission work grouped in one epic).

**Checkpoint:**
```bash
git add -A && git commit -m "step-23: delete confirmed dead code (scoring.py, stats.py, bollinger.py)"
git tag step-23-dead-code-removed
```

---

#### Step 24 — Observation-period gate before removing load-bearing legacy **[ARCHITECTURAL MIGRATION — decommission]**

**Goal:** an explicit, operator-confirmed gate stands between "replacements are tested" and "legacy
is deleted" — this is not code-decidable, and the blueprint says so honestly rather than inventing an
automated proxy for it.

**Files touched:** none (this step produces no code change — it is a checklist/gate)

**Do (nothing programmatic):** confirm, and have the operator confirm, all of the following before
step 25 runs:
1. Steps 12, 13, 20, 21 are deployed to Railway production (not just passing tests locally).
2. `app/notifications/commands.py` has handled at least one real `/portfolio`, `/comprar`, or
   `/vender` command in production since step 21's deploy.
3. The operator has observed the unified system running for a minimum of **7 days** in production
   with no incidents traced back to `portfolio_service.py` or `commands.py`.
4. No code anywhere still imports `portfolio.py`, `telegram_commands.py`, or `signal_manager.py`
   (re-verified mechanically, see Verify below — this part *is* checkable).

**Acceptance criteria (the checkable one):**
1. **WHEN** `grep -rln "^import portfolio\|^from portfolio\|import telegram_commands\|from
   telegram_commands\|import signal_manager\|from signal_manager" app/ run_all.py main.py
   telegram_bot.py` runs **THE SYSTEM SHALL** return zero matches.

**The remaining three conditions above are explicitly NOT build-gate-able** — they require a real
7-day production window and operator judgment. They are a launch/decommission checklist, not a
`pytest` assertion.

**Verify (the mechanical part only):**
```bash
! grep -rln "^import portfolio\|^from portfolio\|import telegram_commands\|from telegram_commands\|import signal_manager\|from signal_manager" app/ run_all.py main.py telegram_bot.py
```

**Depends on:** 21, 22.

**Checkpoint:**
```bash
git add -A && git commit -m "step-24: confirm zero remaining imports of legacy portfolio/telegram_commands/signal_manager"
git tag step-24-legacy-import-free
```

**Operator gate (not code, recorded here for traceability):** operator signs off in writing (e.g. a
line in `docs/BACKLOG.md` or a dated note) that the 7-day observation period is complete before step
25 is executed. The build agent must not proceed to step 25 without this sign-off.

---

#### Step 25 — Delete load-bearing legacy modules **[ARCHITECTURAL MIGRATION — decommission]**

**Goal:** `portfolio.py`, `telegram_commands.py`, `signal_manager.py` are removed — small, final,
easily reverted (single commit, single tag, nothing else changes in this step).

**Files touched:** `portfolio.py` (delete), `telegram_commands.py` (delete), `signal_manager.py`
(delete)

**Do:** delete the three files. Nothing else changes in this step — kept deliberately small so a
revert (`git revert` this single commit) is trivial if something unexpected surfaces.

**Acceptance criteria:**
1. **WHEN** `pytest tests/` runs after deletion **THE SYSTEM SHALL** exit 0.
2. **WHEN** `python -c "import run_all; import telegram_bot; import main"` runs **THE SYSTEM SHALL**
   exit 0.
3. **WHEN** `ls portfolio.py telegram_commands.py signal_manager.py 2>&1` runs **THE SYSTEM SHALL**
   report all three as non-existent.

**Verify:**
```bash
pytest tests/ -q
python -c "import run_all; import telegram_bot; import main"
! ls portfolio.py telegram_commands.py signal_manager.py 2>/dev/null
```

**Depends on:** 24 (gated on the operator sign-off recorded there).

**Checkpoint:**
```bash
git add -A && git commit -m "step-25: remove legacy portfolio.py, telegram_commands.py, signal_manager.py"
git tag step-25-legacy-decommissioned
```

---

## 9.1 Parity and Cutover

This blueprint contains a real migration (Epic 4's portfolio consolidation, Epic 2's schema
constraints). This section is the contract for how old and new coexist, and how the cutover happens.

### Parity checklist

- [ ] Row-count parity: `migrations/0001_portfolio_unify.py` (step 13) asserts
      `portfolio_after = portfolio_before + paper_positions_before`.
- [ ] P&L parity: `scripts/parity_harness_portfolio.py` (step 15) asserts old-formula vs.
      new-service P&L match exactly for every historical `CLOSED` row under the default unconfigured
      `FeeConfig`.
- [ ] Constraint parity: `PRAGMA foreign_key_check` returns zero rows after step 06/07's migration
      (no data violates the new FK before the constraint is turned on).
- [ ] Command parity: step 20's `portfolio_command()` output is manually diffed once against the old
      `telegram_commands.py` output for the same DB state (documented as a one-time manual check in
      that epic's Pitfalls — the only case in this blueprint where output shape, not logic, needs a
      human eyeball, since Telegram message formatting is not meaningfully unit-testable content).

### Parity harness

`scripts/parity_harness_portfolio.py` (step 15) is the automated harness — not a one-off script,
kept in the repo so it can be re-run any time the operator wants confidence the migration held.

### Coexistence plan

Because this is a solo-operator system, the coexistence window is short and explicit rather than a
long dual-write period:

1. **Steps 10–15 (Epic 4):** the new `portfolio` schema and `portfolio_service.py` are built and
   fully tested against migrated data, but `telegram_commands.py` and `portfolio_alerts.py` (before
   step 17) still read the **old** `portfolio.py` module directly. `paper_positions` is not dropped —
   it is marked migrated (`migrated_to_portfolio_id`) but left intact as a safety copy.
2. **Steps 16–17 (Epic 5):** `portfolio_alerts.py` cuts over to `portfolio_service.py` and the alert
   state machine. From this point, alerts are computed from the unified table.
3. **Steps 20–21 (Epic 7):** Telegram commands cut over. This is the moment user-facing behavior
   changes — before step 21, `/portfolio` still shows only stock positions (old code path); after,
   it shows both.
4. **Steps 23–25 (Epic 8):** dead code removed immediately (step 23); load-bearing legacy removed
   only after the 7-day observation gate (step 24) and operator sign-off.

At no point do two code paths **write** to the same table simultaneously — `portfolio.py` is never
edited to also write `asset_class`, it is simply stopped from being called (step 21) and later
deleted (step 25). This avoids a real dual-write consistency problem at the cost of a short window
(steps 10–20) where `portfolio.py` and `portfolio_service.py` both exist but only one is live at a
time per step.

### Numbered cutover sequence with rollback

| # | Action | Rollback |
|---|---|---|
| 1 | Step 10: add columns to `portfolio` | `cp robotinaia.db.backup-step-10 robotinaia.db` |
| 2 | Step 13: migrate `paper_positions` rows in | `cp robotinaia.db.backup-step-13 robotinaia.db` |
| 3 | Step 14: resolve stale BTC-USD (operator-chosen) | `cp robotinaia.db.backup-step-14 robotinaia.db` |
| 4 | Step 17: `portfolio_alerts.py` cuts to new alert state | `git reset --hard step-16-alert-state-machine`, redeploy |
| 5 | Step 21: `telegram_bot.py` cuts to unified commands | `git reset --hard step-20-unified-commands`, redeploy |
| 6 | Step 25: delete legacy modules | `git revert <step-25 commit>` (single small commit, trivial revert) |

### Kill criteria

Abort the cutover and roll back to the previous checkpoint tag if, within the first 24 hours after
any of steps 13, 17, or 21 reach production:

- A Telegram command errors out (`Exception` reaching the bot's top-level handler) where the old code
  path did not.
- `scripts/parity_harness_portfolio.py` run against live production data reports any mismatch.
- Any open position's `stop_loss`/`target_price` displayed via `/portfolio` differs from its value
  immediately before the cutover step (a data-integrity regression, not an intentional trailing-stop
  move).

### Decommission as its own task id

Decommission is `E8-T3` (step 25) in `tasks.json` — a distinct task, gated by `E8-T2` (step 24's
mechanical import-check), never folded into the migration tasks themselves.

---

## 10. Environment Setup

### Prerequisites (developer-installed, not a build step)

- Python 3.12 (matches existing repo; verify with `python --version`).
- `pip` and a virtualenv tool (existing repo convention: `.venv/`, already gitignored).
- `git` ≥ 2.34 (for the operator's `git filter-repo` step in Epic 1 — the build agent does not run
  this, but the tool must exist on the operator's machine).
- `sqlite3` CLI, for the `PRAGMA`/backup verify commands used throughout §9.

### Bootstrap

```bash
# order matters: ignore file already correct (repo has one) → venv → install → verify DB path
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python init_db.py                      # idempotent: create_tables() uses CREATE TABLE IF NOT EXISTS
pytest tests/ -q                       # confirms the environment is sane before any build step starts
```

This repo already has a `.gitignore` covering `.env`, `*.db`, `__pycache__/`, `.venv/` — no new
ignore-file work is needed; `robotinaia.db` was never committed to begin with (`*.db` is ignored), so
the "file you call committed must not be ignored" rule does not apply to it. `.env.example` is
correctly **not** ignored (it must be committed) — Epic 1 fixes its *content*, not its ignore status.

### Environment variables

| Variable | Required by step | Where obtained | Local value |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | all steps that send Telegram messages (03 onward, indirectly) | `@BotFather` on Telegram, rotated per step 01's operator instructions | placeholder in `.env.example`, real value in operator's own `.env` |
| `TELEGRAM_CHAT_ID` | same as above | Telegram (message the bot, read the chat id from any bot-info tool) | placeholder in `.env.example` |
| `DATABASE_PATH` | optional, only set on Railway | Railway volume mount path, e.g. `/data/robotinaia.db` | unset locally — defaults to `robotinaia.db` per `Settings.DATABASE_NAME` |
| `GEMINI_API_KEY` | optional (`scripts/check_gemini.py` only, out of scope for this blueprint) | Google AI Studio | empty locally, unused by this blueprint's steps |

No new environment variables are introduced by this blueprint — `ALERTA_RECORDATORIO_HORAS` (step 16)
and `ALERTA_CAMBIO_MATERIAL_PCT` (step 16) are `Settings` class attributes with hardcoded defaults
(`6` and `0.5`), not env vars, consistent with how the repo already handles tunable constants
(`INTERVALO_REVISION_MINUTOS`, `TRAILING_STEP_PCT`) — no env-loading mechanism is needed for them.

### Database backup/reset commands (used throughout §9)

| Command | Purpose |
|---|---|
| `cp robotinaia.db robotinaia.db.backup-step-NN` | mandatory before every schema-touching step |
| `cp robotinaia.db.backup-step-NN robotinaia.db` | rollback for that step |
| `python init_db.py` | idempotent schema (re)creation on a fresh or existing DB |

---

## 11. Dependencies

No new dependency is added by any step in this blueprint — every step uses `requests`, `pandas`,
`pandas-ta`, `yfinance`, `loguru`, `python-telegram-bot`, `streamlit`, or Python's standard-library
`sqlite3`/`re`/`subprocess`/`abc`, all already in `requirements.txt`.

| Package | Pinned version | Installed by | Purpose in this blueprint |
|---|---|---|---|
| `python-dotenv` | `1.2.2` | `requirements.txt` (pre-existing) | `.env` loading, unchanged |
| `loguru` | `0.7.3` | `requirements.txt` (pre-existing) | logging across every new module |
| `pandas` | `3.0.3` | `requirements.txt` (pre-existing) | `YahooProvider`'s DataFrame handling |
| `pandas-ta` | `0.4.71b0` | `requirements.txt` (pre-existing) | unchanged, RSI/SMA calc untouched |
| `requests` | `2.34.2` | `requirements.txt` (pre-existing) | `YahooProvider`'s retry/backoff HTTP calls (mirrors `BinanceProvider`) |
| `schedule` | `1.2.2` | `requirements.txt` (pre-existing) | unchanged stock scheduler timing |
| `streamlit` | `1.59.2` | `requirements.txt` (pre-existing) | dashboard, service-layer wiring only |
| `python-telegram-bot` | `22.8` | `requirements.txt` (pre-existing) | unified command registration |
| `yfinance` | `1.5.1` | `requirements.txt` (pre-existing) | `YahooProvider`'s underlying data source |
| `pytest` | `9.1.1` | `requirements.txt` (pre-existing, dev) | every new test file in every epic |

**Version provenance:** all versions above are read directly from the repo's own
`requirements.txt` — no `stack-researcher` pin was needed because nothing new is installed. This is a
brownfield change against an existing, working dependency set; introducing a version bump was
explicitly out of scope per the brief ("no new heavyweight dependencies").

### Deliberately not used

| Package | Why not |
|---|---|
| Alembic | `schema.py`'s own docstring already documents the decision to defer it (see BACKLOG Épica 8); this blueprint's `PRAGMA user_version` approach (step 06) is the lighter-weight mechanism the repo chose, consistent with "raw SQL, no ORM." |
| `python-jose` / any JWT lib | no auth model introduced (§8). |
| Any secret-scanning SaaS/pre-commit-hooks framework | step 02's guard script is a plain stdlib script per "no new heavyweight dependencies"; wiring it into an actual git pre-commit hook is a `.git/hooks/pre-commit` one-liner the operator can add locally — not a new dependency. |

---

## 12. Deployment Strategy

Unchanged: Railway, Nixpacks (no Dockerfile), single process `run_all.py`, single persistent volume
holding `robotinaia.db`. This blueprint's only deployment-relevant change is **WAL mode** (step 05):
SQLite WAL creates `robotinaia.db-wal` and `robotinaia.db-shm` sidecar files next to the main DB file.

**Operator action required (not a build step, since it needs the live Railway dashboard):** before
step 05 is deployed to production, confirm Railway's persistent volume correctly persists all three
files (`robotinaia.db`, `robotinaia.db-wal`, `robotinaia.db-shm`) across redeploys — a volume that
only tracks the exact filename `robotinaia.db` would silently lose WAL-pending writes on redeploy.
This is called out again in the Risk Register (§20).

Redeploy trigger: unchanged (git push to the connected branch, per the existing `railway.json`).

---

## 13. Testing Strategy

- **Framework:** `pytest` (already the repo's choice), run via `pytest tests/` or per-file
  (`pytest tests/test_X.py -v`), exactly as used throughout §9's Verify commands.
- **DB isolation:** `tests/conftest.py`'s `db_path` fixture (step 04) — every new test that touches
  SQLite requests it explicitly.
- **No `pytest.ini`/`pyproject.toml` is added** — the repo runs `pytest` with defaults today (test
  discovery via the `test_*.py` naming convention already followed by all 24 existing files), and no
  step in this blueprint needs custom pytest configuration (no markers, no custom paths, no coverage
  gating requested). `conftest.py` alone is sufficient for the DB-isolation fixture this blueprint
  needs; adding a config file with nothing to configure would be exactly the kind of invented
  artifact the brief says not to introduce.
- **New coverage focus, per the brief's explicit priority list:**
  - Unified portfolio P&L including the fee-not-configured flag: `tests/test_portfolio_service.py`,
    `tests/test_fee_config.py` (steps 11–12).
  - Trailing-stop logic — the biggest existing gap: `tests/test_portfolio_service.py`'s trailing-stop
    criteria (step 12, acceptance criteria 3–4).
  - Alert state machine transitions and dedup: `tests/test_alert_state.py`,
    `tests/test_portfolio_alerts_state.py` (steps 16–17).
  - Migration row-count parity: `tests/test_portfolio_migration.py`,
    `tests/test_migration_row_counts.py` (steps 07, 13).
  - The `AlertEngine`/`UMBRAL_SENAL` bug fix: `tests/test_alert.py` (already exists, fixed by step 03,
    not rewritten).
- **Full-suite gate:** `pytest tests/ -q` must exit 0 at the end of every epic (see each epic file's
  "Epic acceptance" section) — this is the retroactive-breakage check from rule 9 applied in practice.

---

## 14. Security & Secrets

- **The leaked Telegram token is Epic 1's entire purpose** — see §9 steps 01–02 and §1's Current
  state. No credential is ever handled programmatically by any build step; every rotation action is
  an operator instruction with a manual verify.
- **`.env` is correctly gitignored today** and stays that way — no change needed.
- **`.env.example` must only ever contain placeholders** — enforced going forward by
  `scripts/check_no_secrets.py` (step 02), which the operator can wire into a local
  `.git/hooks/pre-commit` (one line: `python scripts/check_no_secrets.py || exit 1`) if desired; this
  blueprint does not add a CI pipeline (none exists in the repo today) so "CI guard" in the brief is
  satisfied by the local pre-commit-capable script, documented as such.
- **No new secret is introduced** by any of the 25 steps — `YahooProvider` and `BinanceProvider` both
  hit public, unauthenticated endpoints; the `FeeConfig` interface holds no credentials.

---

## 15. Accessibility

NOT APPLICABLE — no UI is introduced. The Streamlit dashboard's accessibility (or lack thereof) is
unchanged by Epic 7's service-layer refactor, which is explicitly scoped to *data plumbing only*, not
markup or interaction design (§2 Non-Goals).

---

## 16. Observability & Cost

- **Logging:** `loguru`, unchanged — every new module (`yahoo_provider.py`, `portfolio_service.py`,
  `alert_state.py`, `supervisor.py`, `commands.py`) follows the existing convention of
  `logger.info`/`logger.warning`/`logger.exception` at the same granularity `binance_provider.py` and
  `crypto_scheduler.py` already use.
- **New observability surface:** step 19's supervisor escalation Telegram message is the one new
  "something is wrong" signal this blueprint adds — it did not exist before (the old failure mode was
  silent). This is the single most important observability improvement in the blueprint, since it
  converts an invisible failure into a visible one.
- **Cost:** zero new paid services. `YahooProvider` and the guard script add no infrastructure. WAL
  mode adds negligible disk overhead (two small sidecar files). No change to Railway's plan/pricing
  tier is implied by this blueprint.

---

## 17. Model Routing

NOT APPLICABLE — RobotinaIA has no LLM-routing concern in scope here.
`app/ai/ollama_analyzer.py` (used by the legacy `crypto_telegram_commands.py`'s sibling code, not
touched by this blueprint) is out of scope; this blueprint does not add, remove, or route any model
calls.

---

## 18. Skills to Use During Build

| Skill | When to Use | Why | Install |
|---|---|---|---|
| `code-review` | After every epic (01–08), before its final Checkpoint of the epic | Catches correctness/reuse issues in each epic's diff before it is tagged, aligned with the repo's raw-SQL/no-ORM/loguru conventions | Built into Claude Code — invoke as `/code-review` |
| `systematic-debugging` | If any `Verify` command in §9 fails unexpectedly (e.g. step 05's WAL/concurrency test flakes) | Structured root-cause approach before proposing a fix, avoids guessing at SQLite locking behavior | Built into Claude Code — auto-activates on test failures |
| `test-driven-development` | Every step that adds a new module (03, 08, 11, 12, 16, 19, 20, 22) | The brief's whole premise is reliability-through-tests; write the failing test from each step's Acceptance criteria first | Built into Claude Code — auto-activates when writing new modules with tests |

No project-specific UI/design skills apply (§2 NOT APPLICABLE). No skill requiring network research
(`/last30days`, `agent-browser`) is needed — this is a brownfield change against known code, not new
technology selection.

---

## 19. Agent Workspace

### 19.1 `workspace/CLAUDE.md`

See `workspace/CLAUDE.md` in this bundle — written to merge into the repo root. **Brownfield note:**
`C:\Proyectos\RobotinaIA` has no `CLAUDE.md` today, so this is a clean write, not a merge, for this
specific repo — stated here in case this blueprint is ever regenerated after a `CLAUDE.md` already
exists, in which case the builder must merge rather than overwrite.

### 19.2 `workspace/AGENTS.md`

See `workspace/AGENTS.md` — tool-neutral instructions for any non-Claude-Code agent working this
build.

### 19.3 `workspace/.claude/settings.json`

See `workspace/.claude/settings.json`. Every command in every §9 Verify block, plus every §20.1
manual gate command, is in `permissions.allow`.

### 19.4 `workspace/.claude/skills/`

Two repeatable workflows are worth capturing as skills, per the brief's explicit callout:

| Skill | Captures |
|---|---|
| `run-tests` | The full `pytest tests/ -q` gate every epic ends with |
| `backup-db` | The `cp robotinaia.db robotinaia.db.backup-step-NN` pattern every DB-schema-touching step (05, 06, 07, 10, 13, 14) requires before it starts |

See `workspace/.claude/skills/run-tests/SKILL.md` and `workspace/.claude/skills/backup-db/SKILL.md`.

### 19.5 `workspace/.claude/rules/`

| Rule file | Captures |
|---|---|
| `db-schema-changes.md` | The mandatory backup-first + `PRAGMA foreign_key_check` + row-count-parity pattern for any future schema change, generalized from steps 06/07/10/13 |
| `spanish-docstrings-english-identifiers.md` | The repo's existing bilingual convention — Spanish prose in docstrings/comments, English identifiers — so no new module (`yahoo_provider.py`, `portfolio_service.py`, etc.) breaks the pattern |

See `workspace/.claude/rules/db-schema-changes.md` and
`workspace/.claude/rules/spanish-docstrings-english-identifiers.md`.

### 19.6 Verify-critical configuration

**No `pytest.ini`/`pyproject.toml` is emitted** — per §13, the repo runs `pytest tests/` with pure
defaults today (test-file discovery via `test_*.py` naming) and no step in this blueprint needs any
pytest configuration beyond what `tests/conftest.py` (step 04) already provides. This is a deliberate
`NOT APPLICABLE`, not an oversight — the brief explicitly says not to invent one unless a step
legitimately needs it, and none does.

**`tests/conftest.py` IS verify-critical** (every `Verify` command from step 05 onward that touches
the DB depends on the `db_path` fixture it defines) — but unlike the other files in this section, it
is not pre-shipped under `workspace/`. **Step 04 is the step that authors it**, from the blueprint's
own literal content (§9 Step 04's "Do"), so it exists on disk the moment step 04's Checkpoint runs and
every later step's Verify can rely on it. Shipping it under `workspace/` as well would make step 04
gate nothing (its entire deliverable would already exist before the step ran) — so it is deliberately
absent from `workspace/tests/` and lives only as the literal file body inside step 04.

No test-runner-resolution convention (path aliases, import specifiers) applies here — this is a flat
Python package layout (`app.` prefix, standard `sys.path` via the project root), already how every
existing test file imports (`from app.services.alert_engine import AlertEngine`), and pytest resolves
it correctly with zero extra configuration because tests run from the project root, matching the
existing convention exactly. No loader mechanism beyond what already works is introduced.

**Resolution convention matrix**

| Context | Resolved by | Confirm |
|---|---|---|
| App source (`app/...`) | plain Python `import app.x.y`, project root on `sys.path` via CWD | already true today, unchanged |
| Test files (`tests/test_*.py`) | same `import app.x.y`, `pytest` run from project root | already true today (24 existing tests do this), `conftest.py` does not change it |
| Standalone scripts (`migrations/*.py`, `scripts/*.py`) | same convention, run as `python migrations/000X_x.py` from project root | verified per-step in §9's Verify commands, which all `cd`-neutral run from repo root |
| Streamlit dashboard | `sys.path.insert(0, ...)` already present at the top of `dashboard.py` (line 9) — unchanged | confirmed by reading the existing file; step 22 does not touch this line |

**Cross-artifact value reconciliation**

| Value | Owned by | Also appears in | Compared |
|---|---|---|---|
| `robotinaia.db` (DB filename) | `Settings.DATABASE_NAME` (`app/core/settings.py`) | every backup command in §9, `workspace/.claude/skills/backup-db/SKILL.md` | yes — all read the same literal, no step hardcodes a different name |
| `UMBRAL_SENAL = 80` | `app/core/settings.py` (step 03) | `tests/test_alert.py` (pre-existing, unedited), §9 step 03's acceptance criteria | yes — the value is asserted, not duplicated as a separate literal anywhere else |
| `TRAILING_STEP_PCT = 0.03` | `app/alerts/portfolio_alerts.py` (pre-existing) | `app/services/portfolio_service.py` (step 12, imports the same constant rather than redefining it) | yes — step 12's Do explicitly says "matching `portfolio_alerts.py`'s existing constant", not a new literal |
| `ALERTA_RECORDATORIO_HORAS = 6`, `ALERTA_CAMBIO_MATERIAL_PCT = 0.5` | `app/core/settings.py` (step 16) | `app/alerts/alert_state.py` (step 16, reads from `Settings`, does not hardcode) | yes |

**Byte-exact artifact reconciliation**

No step in this blueprint authors a byte-exact golden file, snapshot, or fixture that a `Verify`
command diffs literally — every `Verify` command in §9 asserts either an exit code, a row count, a
`PRAGMA` value, or a Python-level equality assertion inside a `pytest` test (which is data the test
itself computes and compares, not a pre-authored literal string a runtime could contradict). This
table is therefore `NOT APPLICABLE` by construction: `grep`-pattern assertions (step 01, 02) match
against strings this blueprint itself writes into `.env.example` in the same step, so there is no
runtime-dependent wording to reconcile.

---

## 20. Acceptance Gate, Risks & Decision Log

### 20.1 Global acceptance gate

Run from the project root after every step's own Checkpoint, and once more at the very end of the
full 25-step build:

```bash
pytest tests/ -q
git tag -l 'step-*' | wc -l   # expect: 25 (one per step)
python scripts/check_no_secrets.py; test $? -eq 0
sqlite3 robotinaia.db "PRAGMA foreign_key_check;"   # expect: no rows
sqlite3 robotinaia.db "PRAGMA user_version;"        # expect: >= 1, non-decreasing across the build
```

### 20.2 Risk Register

| Risk | Mitigation | Carried by step |
|---|---|---|
| Portfolio merge (Epic 4) silently corrupts or loses historical P&L data | Row-count parity verify (step 13) + independent P&L parity harness (step 15) + mandatory `.db` backup before every schema-touching step | 10, 13, 15 |
| Scheduler supervisor (step 19) masks a real, recurring bug behind endless silent restarts instead of surfacing it | Capped `max_restarts` with a hard Telegram escalation — never restarts forever silently; escalation message includes exception type/message for diagnosis | 19 |
| SQLite WAL mode / schema changes on the live Railway volume behave differently than in local testing (locking, sidecar-file persistence) | Mandatory backup-first Checkpoint on every DB-touching step with a literal restore command; explicit operator confirmation of Railway volume behavior called out before step 05 goes to production (§12) | 05, 06, 07, 10, 13, 14 |
| Stale `BTC-USD` position resolution (step 14) closes or migrates a real financial position incorrectly | Two-flag safety gate (`--action` required, `--confirm-close` required for the close path) — no default, no accidental execution; both paths tested against fixtures before touching the live DB | 14 |
| Operator forgets to complete the token rotation (Epic 1) before this blueprint's other work reaches production | Step 01/02 are ordered first in the build, independent of everything else, and step 02's guard script keeps failing the check_no_secrets gate as a standing reminder if `.env.example` ever regresses | 01, 02 |
| Legacy decommission (Epic 8, step 25) removes a module some overlooked code path still needs | Mechanical import-grep re-check immediately before deletion (step 24) + mandatory 7-day observation gate + tiny, easily-`git revert`-able final commit | 24, 25 |

### 20.3 Decision Log

| Decision | Rationale |
|---|---|
| `UMBRAL_SENAL = 80` | Only value satisfying `tests/test_alert.py`'s existing contract (`65→REVISAR`, `95→OPORTUNIDAD`) and the codebase's round-decade threshold convention (`50` for `REVISAR`) — restores intended behavior, invents no new business rule. |
| `FeeConfig` ships with `fee_pct=0, configured=False` rather than a guessed real fee | Real fee rates are a business fact only the operator knows (brokerage/exchange-specific); inventing one would be exactly the kind of fabricated business decision this blueprint must not make. Flagged as FUTURE IMPROVEMENT (§1). |
| Token rotation, git-history scrub, and the stale-BTC-USD decision are all operator instructions, never code the build agent executes | All three touch real credentials or real money; the brief is explicit that no step may handle these programmatically. |
| `paper_positions` table is kept (not dropped) after migration, marked via `migrated_to_portfolio_id` | Provides a safety copy during the coexistence window (§9.1) without a second live write path — cheaper than a rollback-from-backup if a migration edge case surfaces late. |
| No `pytest.ini`/`pyproject.toml` added | No step needs pytest configuration beyond `conftest.py`; adding one would be an invented artifact the brief explicitly warns against. |
| No CI pipeline added | None exists in the repo today, and none was requested; the secret-guard script degrades gracefully to a local pre-commit hook instead. |

### Blocking gaps

None. Every fact needed to write this blueprint was either in the brief, read directly from the
repo (`app/core/settings.py`, `app/database/schema.py`, `app/services/alert_engine.py`,
`tests/test_alert.py`, `app/providers/binance_provider.py`, `app/strategies/rsi2_connors.py`,
`portfolio.py`, `app/scheduler/repository.py`, `app/paper_trading/repository.py`,
`app/alerts/portfolio_alerts.py`, `run_all.py`, `app/dashboard/dashboard.py`,
`telegram_commands.py`, `app/notifications/crypto_telegram_commands.py`, `.env.example`,
`.gitignore`), or is explicitly delegated to the operator as a labeled instruction (token rotation,
history scrub, stale-position resolution, observation-period sign-off) rather than guessed.

---

## See also

- `epics/01-security-blockers.md` through `epics/08-legacy-decommission.md`
- `tasks.json` — the machine-readable DAG for all 25 steps
- `workspace/CLAUDE.md`, `workspace/AGENTS.md` — merge into `C:\Proyectos\RobotinaIA` root
