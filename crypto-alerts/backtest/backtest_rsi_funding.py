"""
Backtest de las 2 estrategias finalistas sobre las 10 monedas del pipeline,
en una ventana de 730 días (24 meses):

  C) Cruce de EMA (rápida cruza lenta)
  E) Combinada: tendencia SMA200 obligatoria + (RSI extremo O cruce de EMA)

Corre localmente (necesitas internet completo). Usa Binance vía ccxt para
OHLCV (spot) y funding history (futuros perpetuos, no usado por C/E pero se
deja cargado por si vuelves a activar B).

Si tu red/país bloquea Binance, cambia EXCHANGE_ID abajo por 'kucoin'.

ADVERTENCIA DE TIEMPO: con 730 días de velas horarias (~17,500 por moneda)
la descarga puede tardar 15-30 minutos. No cierres la terminal mientras corre.

Uso:
    pip install -r requirements.txt
    python backtest_rsi_funding.py
"""

import time
from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuración general
# ---------------------------------------------------------------------------
EXCHANGE_ID = "binance"
SYMBOLS = ["BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT",
           "DOGE/USDT", "ADA/USDT", "TRX/USDT", "LINK/USDT", "AVAX/USDT"]
TIMEFRAME = "1h"
LOOKBACK_DAYS = 360                  # 24 meses

# RSI (usado solo por E)
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
FUNDING_ANNUALIZED_THRESHOLD = 8.0   # no usado por C/E, se deja por compatibilidad

# EMA (usado por C y E)
EMA_FAST_PERIOD = 12
EMA_SLOW_PERIOD = 26

# Tendencia (usado solo por E)
TREND_SMA_PERIOD = 200

# Gestión de riesgo
SL_PCT = 5.0
TP_PCT = 3.0
MAX_HOLD_HOURS = 14 * 24
COOLDOWN_HOURS = 24


def spot_to_swap_symbol(spot_symbol: str) -> str:
    base, quote = spot_symbol.split("/")
    return f"{base}/{quote}:{quote}"


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
def fetch_ohlcv_full(exchange, symbol, timeframe, since_ms):
    all_rows = []
    since = since_ms
    limit = 1000
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + 1
        if len(batch) < limit:
            break
        time.sleep(exchange.rateLimit / 1000)
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")


def compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["rsi"] = compute_rsi(df["close"], RSI_PERIOD)
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST_PERIOD, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW_PERIOD, adjust=False).mean()
    df["sma_trend"] = df["close"].rolling(TREND_SMA_PERIOD).mean()
    return df


# ---------------------------------------------------------------------------
# Motor de backtest
# ---------------------------------------------------------------------------
def simulate_trades(df, long_cond, short_cond, label, warmup):
    trades = []
    last_exit_idx = -10 ** 9

    for i in range(warmup, len(df) - 1):
        if i - last_exit_idx < COOLDOWN_HOURS:
            continue

        direction = None
        if short_cond(df, i):
            direction = "CORTO"
        elif long_cond(df, i):
            direction = "LARGO"
        if direction is None:
            continue

        entry_price = df.iloc[i]["close"]
        if direction == "CORTO":
            sl_price = entry_price * (1 + SL_PCT / 100)
            tp_price = entry_price * (1 - TP_PCT / 100)
        else:
            sl_price = entry_price * (1 - SL_PCT / 100)
            tp_price = entry_price * (1 + TP_PCT / 100)

        outcome, exit_i = None, None
        for j in range(i + 1, min(i + 1 + MAX_HOLD_HOURS, len(df))):
            hi, lo = df.iloc[j]["high"], df.iloc[j]["low"]
            if direction == "CORTO":
                hit_sl, hit_tp = hi >= sl_price, lo <= tp_price
            else:
                hit_sl, hit_tp = lo <= sl_price, hi >= tp_price
            if hit_sl and hit_tp:
                outcome, exit_i = "SL", j
                break
            if hit_sl:
                outcome, exit_i = "SL", j
                break
            if hit_tp:
                outcome, exit_i = "TP", j
                break
        if outcome is None:
            outcome, exit_i = "TIMEOUT", min(i + MAX_HOLD_HOURS, len(df) - 1)

        pnl_pct = TP_PCT if outcome == "TP" else (-SL_PCT if outcome == "SL" else 0.0)
        trades.append({
            "estrategia": label, "direccion": direction, "entrada_ts": df.index[i],
            "salida_ts": df.index[exit_i], "resultado": outcome, "pnl_pct": pnl_pct,
        })
        last_exit_idx = exit_i

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, symbol: str):
    if trades.empty:
        return {"symbol": symbol, "trades": 0, "wins": 0, "losses": 0,
                "timeouts": 0, "win_rate_%": 0.0, "pnl_acumulado_%": 0.0}
    wins = (trades["resultado"] == "TP").sum()
    losses = (trades["resultado"] == "SL").sum()
    timeouts = (trades["resultado"] == "TIMEOUT").sum()
    total = len(trades)
    win_rate = wins / total * 100 if total else 0
    return {
        "symbol": symbol, "trades": total, "wins": wins, "losses": losses,
        "timeouts": timeouts, "win_rate_%": round(win_rate, 1),
        "pnl_acumulado_%": round(trades["pnl_pct"].sum(), 1),
    }


def print_and_save(results: dict, label: str, filename: str):
    df = pd.DataFrame(results)
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    print(df.to_string(index=False))
    if df["trades"].sum() > 0:
        print(f"\nTOTAL -> Trades: {df['trades'].sum()} | "
              f"Win rate global: {df['wins'].sum() / df['trades'].sum() * 100:.1f}% | "
              f"PnL acumulado: {df['pnl_acumulado_%'].sum():.1f}%")
    df.to_csv(filename, index=False)


# ---------------------------------------------------------------------------
# Estrategias finalistas
# ---------------------------------------------------------------------------
def strategy_C(df, i):
    prev, cur = df.iloc[i - 1], df.iloc[i]
    golden_cross = prev["ema_fast"] <= prev["ema_slow"] and cur["ema_fast"] > cur["ema_slow"]
    death_cross = prev["ema_fast"] >= prev["ema_slow"] and cur["ema_fast"] < cur["ema_slow"]
    return golden_cross, death_cross


def strategy_E(df, i):
    row = df.iloc[i]
    trend = row.get("sma_trend", np.nan)
    if pd.isna(trend):
        return False, False
    prev, cur = df.iloc[i - 1], df.iloc[i]
    golden_cross = prev["ema_fast"] <= prev["ema_slow"] and cur["ema_fast"] > cur["ema_slow"]
    death_cross = prev["ema_fast"] >= prev["ema_slow"] and cur["ema_fast"] < cur["ema_slow"]

    long_ = row["close"] > trend and (row["rsi"] < RSI_OVERSOLD or golden_cross)
    short_ = row["close"] < trend and (row["rsi"] > RSI_OVERBOUGHT or death_cross)
    return long_, short_


# Solo las 2 finalistas activas -- A, B y D quedaron fuera de esta corrida
STRATEGIES = {
    "C_cruce_EMA": (strategy_C, EMA_SLOW_PERIOD + 1),
    "E_combinada": (strategy_E, max(EMA_SLOW_PERIOD + 1, TREND_SMA_PERIOD)),
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    spot_exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})

    since_dt = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    since_ms = int(since_dt.timestamp() * 1000)

    results = {name: [] for name in STRATEGIES}

    for symbol in SYMBOLS:
        print(f"\nProcesando {symbol} ...")
        df = fetch_ohlcv_full(spot_exchange, symbol, TIMEFRAME, since_ms)
        df = add_indicators(df)

        for name, (cond_fn, warmup) in STRATEGIES.items():
            long_cond = lambda d, idx, fn=cond_fn: fn(d, idx)[0]
            short_cond = lambda d, idx, fn=cond_fn: fn(d, idx)[1]
            trades = simulate_trades(df, long_cond, short_cond, name, warmup)
            results[name].append(summarize(trades, symbol))

    print("\n" + "#" * 70)
    print(f"# FINALISTAS (C vs E) | {LOOKBACK_DAYS} días | SL {SL_PCT}% / TP {TP_PCT}%")
    print("#" * 70)

    totals = []
    for name in STRATEGIES:
        filename = f"resultados_estrategia_{name}_730d.csv"
        print_and_save(results[name], name, filename)
        df_r = pd.DataFrame(results[name])
        t = df_r["trades"].sum()
        wr = df_r["wins"].sum() / t * 100 if t else 0
        pnl = df_r["pnl_acumulado_%"].sum()
        totals.append({"estrategia": name, "trades": t, "win_rate_%": round(wr, 1), "pnl_total_%": round(pnl, 1)})

    print("\n" + "=" * 70)
    print("RESUMEN FINAL -- C vs E a 730 días")
    print("=" * 70)
    print(pd.DataFrame(totals).to_string(index=False))
    print("\nResultados detallados guardados en resultados_estrategia_*_730d.csv")


if __name__ == "__main__":
    main()