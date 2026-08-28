# Epic 03: Unified Market-Data Provider

> After this epic, stocks get the same retry/backoff resilience crypto already has via
> `YahooProvider`, and `rsi2_connors.py` uses it — with zero change to the RSI(2)-Connors signal math.

| | |
|---|---|
| **Epic id** | `03-unified-market-data-provider` |
| **Tasks** | `E3-T1` … `E3-T2` |
| **Depends on** | nothing |
| **Unlocks** | `04-unified-portfolio-and-pnl` (E4-T5 needs `YahooProvider` for the stale-BTC close path) |
| **Parallel with** | `01-security-blockers`, `02-database-integrity-and-concurrency` |

You do not need any other file to complete this epic. Everything below is repeated here on purpose.

---

## Stack

Python 3.12 · `yfinance` 1.5.1 · `requests` 2.34.2 · `pandas` 3.0.3 · `loguru` · `pytest`.

| Task | Command |
|---|---|
| Test (one file) | `pytest tests/test_X.py -v` |
| Test (all) | `pytest tests/ -q` |

**Gate:** `pytest tests/test_yahoo_provider.py tests/test_rsi2_connors_provider.py tests/test_score.py -v`
passes before either task here is marked done.

No local service needed — tests mock `yf.Ticker.history`, they do not require live network.

## Directory subtree

```
app/
  providers/
    market_data_provider.py   # exists, read-only — the ABC contract this epic implements
    binance_provider.py       # exists, read-only — the reference pattern to mirror
    yahoo_provider.py         # NEW (E3-T1)
  strategies/
    rsi2_connors.py           # EDIT (E3-T2) — data source only, signal logic untouched
tests/
  test_yahoo_provider.py            # NEW (E3-T1)
  test_rsi2_connors_provider.py     # NEW (E3-T2)
  test_score.py                     # exists, read-only — re-run to confirm no signal-logic regression
```

## Data model touched here

NOT APPLICABLE — no database change in this epic.

## Contracts

**Consumed** — already exists, do not rebuild:

| From | Interface | Guarantee |
|---|---|---|
| `app/providers/market_data_provider.py` | `MarketDataProvider.get_stock(symbol) -> Stock` | abstract contract `YahooProvider` must implement |
| `app/providers/binance_provider.py` | `BinanceProvider`'s retry/backoff shape (`MAX_REINTENTOS`, exponential sleep) | the pattern to mirror, not to import — `YahooProvider` is a sibling implementation, not a subclass |

**Produced** — later epics depend on exactly these signatures:

| Export | Signature | Used by |
|---|---|---|
| `app/providers/yahoo_provider.YahooProvider` | `get_stock(symbol: str) -> Stock`, `get_daily_history(symbol: str, period: str) -> pd.DataFrame` | `app/strategies/rsi2_connors.py` (this epic), `migrations/0002_resolve_stale_btc.py` (Epic 4, E4-T5) |
| `app/providers/yahoo_provider.YahooProviderError` | `Exception` subclass | any caller needing to catch provider failures distinctly |

## Conventions that bite in this area

- `YahooProvider` is a **sibling** of `BinanceProvider`, not built on top of it — they share a pattern
  (retry count, backoff shape, error type naming), not code. Do not introduce a shared base class;
  that would be new architecture beyond this blueprint's scope.
- `get_daily_history` is **not** part of the `MarketDataProvider` ABC — same precedent as
  `BinanceProvider.get_ohlcv`, which also lives outside the minimal `get_stock` contract because the
  ABC's single-price return shape cannot represent a DataFrame.
- **The RSI(2)-Connors entry/exit math (`_hubo_cruce_entrada_hoy`, `_hubo_condicion_salida_hoy`,
  `RSI_ENTRADA`, `RSI_SALIDA`, `SMA_PERIODO`) must not change.** This epic only replaces *how the data
  arrives*, never *what is done with it*.

Full project rules: `CLAUDE.md`. Area rules: `.claude/rules/spanish-docstrings-english-identifiers.md`.

---

## Tasks

### `E3-T1` — Add `YahooProvider` with retry/backoff

**Depends on:** nothing · **Priority:** p0

Implement `YahooProvider(MarketDataProvider)` in `app/providers/yahoo_provider.py`, mirroring
`BinanceProvider`'s shape: `MAX_REINTENTOS = 3`, exponential backoff
(`time.sleep(2 ** intento)`) around `yf.Ticker(symbol).history(...)` calls, catching broad
`Exception` (unlike Binance, `yfinance` does not expose stable HTTP status codes through its API, so
this cannot be narrowed to specific status codes the way `BinanceProvider._pedir_futures` does —
document this difference in the module docstring). An empty returned DataFrame is treated as
`YahooProviderError`, matching `BinanceProviderError`'s "empty response is an error" convention.
`get_stock(symbol)` wraps `history(period="1d", interval="5m")` and returns the last close as a
`Stock` (same call shape already used ad hoc in `portfolio_alerts.py`).

**Files**
- `app/providers/yahoo_provider.py` — new.
- `tests/test_yahoo_provider.py` — new, mocks `yf.Ticker.history`.

**Acceptance**

1. **WHEN** `YahooProvider().get_stock("AAPL")` is called against a working network **THE SYSTEM
   SHALL** return a `Stock` with a positive `price`.
2. **WHEN** `yf.Ticker.history` is mocked to raise on the first 2 calls and succeed on the 3rd
   **THE SYSTEM SHALL** return successfully, calling the mock exactly 3 times.
3. **WHEN** `yf.Ticker.history` is mocked to always raise **THE SYSTEM SHALL** raise
   `YahooProviderError` after exactly `MAX_REINTENTOS` attempts.
4. **WHEN** `yf.Ticker.history` returns an empty DataFrame **THE SYSTEM SHALL** raise
   `YahooProviderError`.

**Verify**

```bash
pytest tests/test_yahoo_provider.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E3-T1: add YahooProvider with retry/backoff, mirrors BinanceProvider"
git tag step-08-yahoo-provider
```

### `E3-T2` — Wire `rsi2_connors.py` to `YahooProvider`

**Depends on:** `E3-T1` · **Priority:** p0

Add `get_daily_history(symbol, period)` to `YahooProvider` (wraps `history(period=period,
interval="1d")` with the same retry/backoff as `get_stock`). Replace
`_cargar_datos_diarios`'s direct `yf.Ticker(symbol).history(period=PERIODO_DESCARGA, interval="1d")`
call with `YahooProvider().get_daily_history(symbol, PERIODO_DESCARGA)`. Every downstream function
(`_limpiar_datos`, `_calcular_indicadores`, `_hubo_cruce_entrada_hoy`, `_hubo_condicion_salida_hoy`)
is untouched.

**Files**
- `app/strategies/rsi2_connors.py` — edit.
- `tests/test_rsi2_connors_provider.py` — new.

**Acceptance**

1. **WHEN** `_cargar_datos_diarios("AAPL")` is called **THE SYSTEM SHALL** return the same DataFrame
   shape it returned before this change, verified against a recorded fixture.
2. **WHEN** the underlying data source fails transiently **THE SYSTEM SHALL** retry via
   `YahooProvider`'s backoff instead of failing on the first attempt.
3. **WHEN** `ejecutar_rsi2_connors()` runs against a fixture where one symbol's fetch fails
   permanently **THE SYSTEM SHALL** log and continue to the next symbol.
4. **WHEN** `pytest tests/test_score.py` is re-run **THE SYSTEM SHALL** still pass.

**Verify**

```bash
pytest tests/test_rsi2_connors_provider.py -v
pytest tests/test_score.py -v
```

**Checkpoint**

```bash
git add -A && git commit -m "E3-T2: wire rsi2_connors.py to YahooProvider, no signal-logic change"
git tag step-09-rsi2-yahoo-provider-wired
```

---

## Epic acceptance

1. **WHEN** `rsi2_connors.py`'s daily data fetch is called **THE SYSTEM SHALL** route through
   `YahooProvider` and retry on transient failure.
2. **WHEN** `pytest tests/` runs **THE SYSTEM SHALL** exit 0, including the pre-existing scoring tests
   this epic must not regress.

```bash
pytest tests/test_yahoo_provider.py tests/test_rsi2_connors_provider.py tests/test_score.py -v
```

## Pitfalls

- **Do not narrow `YahooProvider`'s exception handling to specific HTTP codes the way
  `BinanceProvider` does.** `yfinance` does not expose them reliably; broad `except Exception` with
  logging is the honest, tested pattern here.
- **Do not touch `RSI_ENTRADA`, `RSI_SALIDA`, `SMA_PERIODO`, or any function computing signals.** This
  epic is data-source plumbing only.

## Before moving on

- [ ] Both tasks `done` in `tasks.json`.
- [ ] `step-08-yahoo-provider` and `step-09-rsi2-yahoo-provider-wired` tags exist.
- [ ] `tests/test_score.py` still passes unchanged (proves no signal-logic regression).
- [ ] No file outside the subtree was modified.
