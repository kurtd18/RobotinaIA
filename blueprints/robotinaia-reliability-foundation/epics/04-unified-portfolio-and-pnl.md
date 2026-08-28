# Epic 04: Unified Portfolio & P&L

> After this epic, one `portfolio` table and one `portfolio_service.py` own buy/sell/trailing-stop/P&L
> for both stocks and crypto, fees are surfaced honestly via `FeeConfig`, historical data is migrated
> with row-count and P&L parity proven, and the stale `BTC-USD` position has operator-driven tooling
> to resolve it.

| | |
|---|---|
| **Epic id** | `04-unified-portfolio-and-pnl` |
| **Tasks** | `E4-T1` … `E4-T6` |
| **Depends on** | `02-database-integrity-and-concurrency` (E2-T5), `03-unified-market-data-provider` (E3-T2, for E4-T5 only) |
| **Unlocks** | `05-alert-reliability`, `07-telegram-dashboard-consolidation` (E7-T1) |
| **Parallel with** | `06-scheduler-resilience` |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · SQLite via raw `sqlite3` · `loguru` · `pytest`. No ORM, no new dependency.

| Task | Command |
|---|---|
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |
| Backup before schema change | `cp robotinaia.db robotinaia.db.backup-step-NN` |
| Run a migration script | `python migrations/000X_name.py` |

**Gate:** `pytest tests/test_portfolio_service.py tests/test_fee_config.py
tests/test_portfolio_migration.py tests/test_resolve_stale_btc.py tests/test_parity_harness.py -v`
passes before any task here is marked done.

`E4-T1`, `E4-T4`, `E4-T5` touch the live `robotinaia.db` — back it up first, always.

## Directory subtree

```
app/
  database/
    schema.py                      # EDIT (E4-T1) — asset_class, normalized_symbol, fee columns
    migrations.py                  # EDIT (E4-T1) — new migration entry
  services/
    fee_config.py                  # NEW (E4-T2)
    portfolio_service.py           # NEW (E4-T3)
    symbol_normalization.py        # NEW (E4-T3) — shared BTC-USD/BTCUSDT -> BTC mapping
migrations/
  0001_portfolio_unify.py          # NEW (E4-T4)
  0002_resolve_stale_btc.py        # NEW (E4-T5)
scripts/
  parity_harness_portfolio.py      # NEW (E4-T6)
tests/
  test_schema_constraints.py       # EDIT (E4-T1) — new cases added
  test_fee_config.py               # NEW (E4-T2)
  test_portfolio_service.py        # NEW (E4-T3)
  test_portfolio_migration.py      # NEW (E4-T4)
  test_resolve_stale_btc.py        # NEW (E4-T5)
  test_parity_harness.py           # NEW (E4-T6)
```

## Data model touched here

| Entity | Fields this epic adds or reads | Notes |
|---|---|---|
| `portfolio` | `+normalized_symbol TEXT NOT NULL`, `+asset_class TEXT NOT NULL CHECK IN ('stock','crypto')`, `+fee_pct_applied REAL`, `+fees_included INTEGER NOT NULL DEFAULT 0` | migration backfills existing rows |
| `paper_positions` | `+migrated_to_portfolio_id INTEGER` | traceability column added by `0001_portfolio_unify.py`; table itself is NOT dropped |

## Contracts

**Consumed** — already exists, do not rebuild:

| From | Interface | Guarantee |
|---|---|---|
| `02-database-integrity-and-concurrency` | `app/database/connection.get_connection()`, `app/database/migrations.apply_migrations(conn)` | WAL/FK-ready connection, versioned migration hook |
| `03-unified-market-data-provider` | `app/providers/yahoo_provider.YahooProvider().get_stock(symbol)` | live price for the stale-BTC close path (E4-T5 only) |
| `portfolio.py` (legacy, still present) | `TRAILING_STEP_PCT = 0.03` | E4-T3 imports this constant rather than redefining it |
| `app/alerts/portfolio_alerts.py` (legacy) | `_revisar_trailing_stop`'s math shape | E4-T3 ports this logic, does not invent new trailing-stop rules |

**Produced** — later epics depend on exactly these signatures:

| Export | Signature | Used by |
|---|---|---|
| `app/services/portfolio_service.add_position` | `(symbol, quantity, buy_price, asset_class, target_price=None, stop_loss=None) -> int` | `05-alert-reliability`, `07-telegram-dashboard-consolidation` |
| `app/services/portfolio_service.sell_position` | `(position_id, sell_price) -> dict` (includes `fees_included`) | same |
| `app/services/portfolio_service.get_open_positions` | `() -> list[dict]` | same |
| `app/services/fee_config.STOCK_FEE_CONFIG`, `CRYPTO_FEE_CONFIG` | `FeeConfig` instances, `configured=False` by default | `portfolio_service.sell_position` |

## Conventions that bite in this area

- **Never invent a real fee rate.** `FeeConfig` ships `fee_pct=0.0, configured=False` — entering real
  fees is the operator's job later, out of scope here (see blueprint §1 Non-Goals).
- **Closing the stale BTC-USD position is a financial decision, never code's to make unilaterally.**
  `0002_resolve_stale_btc.py` requires an explicit `--action` flag with no default, and the close path
  additionally requires `--confirm-close`.
- **`paper_positions` is never dropped in this epic** — it stays as a safety copy during the
  coexistence window (blueprint §9.1), marked via `migrated_to_portfolio_id`.
- **No dual-write.** Once `portfolio_service.py` exists, `portfolio.py` keeps working exactly as
  before until Epic 7 stops calling it — this epic never edits `portfolio.py` to also write the new
  columns.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/db-schema-changes.md`.

---

## Tasks

### `E4-T1` — Add `asset_class`/`normalized_symbol`/fee columns to `portfolio`

**Depends on:** nothing beyond Epic 2 (already unlocked) · **Priority:** p0

Extend `SCHEMA_PORTFOLIO` with the four new columns. Add a migration entry in
`app/database/migrations.py` that, for every existing row, sets `asset_class` (`'crypto'` if the
symbol is in `Settings.ACTIVOS_CRIPTO`, else `'stock'`), `normalized_symbol` (via the shared mapping
from `app/services/symbol_normalization.py` — write this tiny helper module now, even though
`portfolio_service.py` proper lands in E4-T3, since both the migration and the service need the exact
same mapping and must not each define their own copy), `fees_included=0`, `fee_pct_applied=NULL`.

**Files**
- `app/database/schema.py` — edit.
- `app/database/migrations.py` — edit.
- `app/services/symbol_normalization.py` — new (the shared mapping, used here and by E4-T3).
- `tests/test_schema_constraints.py` — edit, add portfolio-asset-class cases.

**Acceptance**

1. **WHEN** the migration runs against a DB containing the current `BTC-USD` id=2 row **THE SYSTEM
   SHALL** set `asset_class='crypto'`, `normalized_symbol='BTC'` on that row.
2. **WHEN** the migration runs against existing stock rows **THE SYSTEM SHALL** set
   `asset_class='stock'`, `normalized_symbol` equal to the existing `symbol`.
3. **WHEN** an `INSERT INTO portfolio` supplies `asset_class='option'` **THE SYSTEM SHALL** raise
   `sqlite3.IntegrityError`.
4. **WHEN** the migration runs twice **THE SYSTEM SHALL** be idempotent.

**Verify**

```bash
cp robotinaia.db robotinaia.db.backup-step-10
pytest tests/test_schema_constraints.py -k portfolio_asset_class -v
sqlite3 robotinaia.db "SELECT symbol, asset_class, normalized_symbol FROM portfolio;"
```

**Checkpoint**

```bash
git add -A && git commit -m "E4-T1: add asset_class/normalized_symbol/fee columns to portfolio"
git tag step-10-portfolio-schema-delta
```

Rollback if needed: `cp robotinaia.db.backup-step-10 robotinaia.db`.

### `E4-T2` — Add `FeeConfig` strategy interface

**Depends on:** nothing · **Priority:** p0

`app/services/fee_config.py`: `FeeConfig(ABC)` with `apply(gross_pnl, quantity, price) -> tuple[float,
bool]`; default `FlatPercentageFeeConfig(fee_pct=0.0, configured=False)`; module-level
`STOCK_FEE_CONFIG`, `CRYPTO_FEE_CONFIG` instances, both unconfigured by default.

**Files**
- `app/services/fee_config.py` — new.
- `tests/test_fee_config.py` — new.

**Acceptance**

1. **WHEN** `STOCK_FEE_CONFIG.apply(100.0, 10, 50.0)` is called with defaults **THE SYSTEM SHALL**
   return `(100.0, False)`.
2. **WHEN** a `FlatPercentageFeeConfig(fee_pct=0.1, configured=True)` is applied to a `100.0` gross
   P&L **THE SYSTEM SHALL** return a value less than `100.0` and `configured=True`.
3. **WHEN** `fee_pct` is negative **THE SYSTEM SHALL** raise `ValueError` at construction.

**Verify**

```bash
pytest tests/test_fee_config.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E4-T2: add FeeConfig strategy interface, defaults unconfigured"
git tag step-11-fee-config
```

### `E4-T3` — Add `portfolio_service.py`: unified buy/sell/trailing-stop/P&L

**Depends on:** `E4-T1`, `E4-T2` · **Priority:** p0

Port `add_position`, `get_open_positions`, `sell_position`, `actualizar_trailing_stop`,
`marcar_alerta_stop`, `registrar_decision` from `portfolio.py` into
`app/services/portfolio_service.py`, adding an `asset_class` parameter and writing
`normalized_symbol` via `symbol_normalization.py`. `sell_position` runs P&L through the asset class's
`FeeConfig.apply(...)`, storing `fee_pct_applied`/`fees_included`. Trailing-stop math is a direct port
of `portfolio_alerts.py`'s `_revisar_trailing_stop` logic and `TRAILING_STEP_PCT` constant (imported,
not redefined) — this is the epic covering the blueprint's biggest test-coverage gap.

**Files**
- `app/services/portfolio_service.py` — new.
- `tests/test_portfolio_service.py` — new.

**Acceptance**

1. **WHEN** `add_position("BTC-USD", 0.01, 50000, asset_class="crypto")` is called **THE SYSTEM
   SHALL** insert a row with `normalized_symbol='BTC'`.
2. **WHEN** `sell_position` is called under the default unconfigured `FeeConfig` **THE SYSTEM SHALL**
   compute P&L identically to `(sell_price - buy_price) * quantity` and set `fees_included=0`.
3. **WHEN** price crosses `target_price` in a simulated trailing-stop cycle **THE SYSTEM SHALL** raise
   `stop_loss` to the old `target_price` and raise `target_price` by exactly 3%.
4. **WHEN** trailing-stop is applied twice in sequence **THE SYSTEM SHALL** compound correctly.
5. **WHEN** `sell_position` is called with a configured `FeeConfig(fee_pct=0.001, configured=True)`
   **THE SYSTEM SHALL** report `fees_included=1` and a strictly lower P&L than the fee-unaware
   calculation for a profitable trade.

**Verify**

```bash
pytest tests/test_portfolio_service.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E4-T3: add portfolio_service.py, unified buy/sell/trailing-stop/P&L, fee-aware"
git tag step-12-portfolio-service
```

### `E4-T4` — Migrate `portfolio` + `paper_positions` into unified schema, row-count parity

**Depends on:** `E4-T3` · **Priority:** p0

`migrations/0001_portfolio_unify.py`: counts `portfolio`/`paper_positions` rows before; for each
`paper_positions` row, inserts an equivalent `portfolio` row via `symbol_normalization.py`'s mapping;
leaves `paper_positions` intact, marking migrated rows via `migrated_to_portfolio_id`; asserts
`portfolio_after == portfolio_before + paper_positions_before`; exits 1 on mismatch; idempotent
(re-run skips already-migrated rows).

**Files**
- `migrations/0001_portfolio_unify.py` — new.
- `tests/test_portfolio_migration.py` — new.

**Acceptance**

1. **WHEN** the migration runs against a copy of the live DB **THE SYSTEM SHALL** report
   `portfolio` row count after equal to before plus `paper_positions` before, and exit 0.
2. **WHEN** run against a fixture with 3 `paper_positions` rows and 2 `portfolio` rows
   **THE SYSTEM SHALL** produce exactly 5 `portfolio` rows after.
3. **WHEN** a `paper_positions` row has an unrecognized symbol **THE SYSTEM SHALL** log a warning,
   skip it, and report it in the final summary.
4. **WHEN** run a second time **THE SYSTEM SHALL** skip already-migrated rows (idempotent).

**Verify**

```bash
cp robotinaia.db robotinaia.db.backup-step-13
cp robotinaia.db /tmp/migration_test.db
python migrations/0001_portfolio_unify.py
pytest tests/test_portfolio_migration.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E4-T4: migrate portfolio + paper_positions into unified schema, parity verified"
git tag step-13-portfolio-migration
```

Rollback if needed: `cp robotinaia.db.backup-step-13 robotinaia.db`.

### `E4-T5` — Tooling to resolve stale BTC-USD position (operator chooses)

**Depends on:** `E4-T4`, `E3-T2` · **Priority:** p0

`migrations/0002_resolve_stale_btc.py`, two modes gated by `--action=close|migrate` (no default; bare
invocation prints both options and exits 2). `--action=migrate` leaves the position `OPEN`, fully
unified. `--action=close` additionally requires `--confirm-close`; fetches the current price via
`YahooProvider().get_stock("BTC-USD")` and calls `portfolio_service.sell_position(2, current_price)`.
**This task's acceptance is about the tooling's safety, not which path the operator eventually
picks** — see blueprint §9.1 for the coexistence/cutover framing.

**Files**
- `migrations/0002_resolve_stale_btc.py` — new.
- `tests/test_resolve_stale_btc.py` — new.

**Acceptance**

1. **WHEN** run with no flags **THE SYSTEM SHALL** print both options and exit 2, taking no DB action.
2. **WHEN** run with `--action=migrate` **THE SYSTEM SHALL** leave the position `status='OPEN'` and
   set its `asset_class`/`normalized_symbol`.
3. **WHEN** run with `--action=close` but without `--confirm-close` **THE SYSTEM SHALL** exit 2,
   taking no DB action.
4. **WHEN** run with `--action=close --confirm-close` against a test fixture **THE SYSTEM SHALL** set
   `status='CLOSED'` with a `sell_price` from `YahooProvider` and a non-null `sell_date`.

**Verify**

```bash
cp robotinaia.db robotinaia.db.backup-step-14
python migrations/0002_resolve_stale_btc.py; test $? -eq 2
pytest tests/test_resolve_stale_btc.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E4-T5: tooling to resolve stale BTC-USD position (operator chooses close/migrate)"
git tag step-14-stale-btc-tooling
```

Rollback if needed: `cp robotinaia.db.backup-step-14 robotinaia.db`. **Operator action still required
in production**: run the script against the real DB with the chosen flag — the build agent ships the
tool, never the decision.

### `E4-T6` — Add old-vs-new P&L parity harness

**Depends on:** `E4-T4` · **Priority:** p1

`scripts/parity_harness_portfolio.py`: for every `CLOSED` row migrated by E4-T4, recompute P&L via
the old inline formula and via `portfolio_service`'s fee-aware path (unconfigured `FeeConfig`, which
must match exactly since `fee_pct=0`); assert equality per row; exit 1 on mismatch.

**Files**
- `scripts/parity_harness_portfolio.py` — new.
- `tests/test_parity_harness.py` — new.

**Acceptance**

1. **WHEN** the harness runs against the migrated DB **THE SYSTEM SHALL** report 0 mismatches and
   exit 0.
2. **WHEN** a mismatch is injected in a test fixture **THE SYSTEM SHALL** detect it, print the row id
   and both values, and exit 1.

**Verify**

```bash
python scripts/parity_harness_portfolio.py
pytest tests/test_parity_harness.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E4-T6: add old-vs-new P&L parity harness"
git tag step-15-parity-harness
```

---

## Epic acceptance

1. **WHEN** `pytest tests/` runs **THE SYSTEM SHALL** exit 0, including every new file in this epic.
2. **WHEN** `scripts/parity_harness_portfolio.py` runs against the migrated DB **THE SYSTEM SHALL**
   report zero P&L mismatches.

```bash
pytest tests/test_portfolio_service.py tests/test_fee_config.py tests/test_portfolio_migration.py tests/test_resolve_stale_btc.py tests/test_parity_harness.py -v
python scripts/parity_harness_portfolio.py
```

## Pitfalls

- **Do not invent a real fee number.** `configured=False` is the correct, honest default.
- **Do not let `0002_resolve_stale_btc.py` default to any action.** Bare invocation must be a no-op
  that only prints options — a default here is exactly the kind of unilateral financial decision the
  brief forbids code from making.
- **`portfolio.py` is not edited in this epic.** It keeps running exactly as before; only new code is
  added alongside it (coexistence window, blueprint §9.1).

## Before moving on

- [ ] All 6 tasks `done` in `tasks.json`.
- [ ] Tags `step-10` through `step-15` exist.
- [ ] `robotinaia.db.backup-step-10`, `-13`, `-14` exist on disk.
- [ ] Parity harness (E4-T6) reports zero mismatches against the actual migrated data, not only test
      fixtures.
- [ ] No file outside the subtree was modified.
