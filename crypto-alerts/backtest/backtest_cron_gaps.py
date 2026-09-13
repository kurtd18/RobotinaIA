"""
Backtest comparativo: ¿el fix del cron (corridas parejas cada 4h + ventana
de cruce ampliada a 6 velas + dedup) realmente cierra el hueco de cruces
EMA perdidos, sin perjudicar el resultado de la estrategia?

Compara 3 escenarios sobre los 4 símbolos de producción (XRP, ETH, DOGE,
SOL), 360 días de velas 1h, misma regla de entrada que
crypto-alerts/analyze_and_notify.py (estrategia E: SMA200 obligatoria +
(RSI extremo O cruce EMA reciente)):

  IDEAL    - evaluado cada hora (cota superior teórica, sin restricción
             de cron; equivalente a "estrategia E combinada" ya validada
             en backtest_rsi_funding.py)
  ANTES    - cron viejo (14:07, 18:07, 22:07 UTC - hueco de 16h) +
             ventana de cruce de 3 velas, sin dedup
  DESPUES  - cron nuevo (02,06,10,14,18,22 UTC cada 4h) + ventana de
             cruce de 6 velas + dedup por timestamp (igual a la lógica
             real de evaluar_senal en producción)

Métrica clave: cuántos cruces EMA reales (golden/death, detectados en el
escenario IDEAL) caen fuera de la ventana de detección de cada cron
("cruces perdidos"), y cómo afecta eso al número de señales y al PnL.

Uso:
    pip install -r requirements.txt
    python backtest_cron_gaps.py
"""

import time
from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd

EXCHANGE_ID = "binance"
SYMBOLS = ["XRP/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT"]
TIMEFRAME = "1h"
LOOKBACK_DAYS = 730

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
EMA_FAST_PERIOD = 12
EMA_SLOW_PERIOD = 26
TREND_SMA_PERIOD = 200

MAX_HOLD_HOURS = 14 * 24
COOLDOWN_HOURS = 24

# Ratios riesgo/beneficio a comparar, todos sobre el cron DESPUES (el que
# va a producción). "actual" es el que corre hoy en analyze_and_notify.py.
CONFIGS_SL_TP = {
    "actual (5% SL / 3% TP, ratio 1:0.6)": (5.0, 3.0),
    "1:1 (3% SL / 3% TP)": (3.0, 3.0),
    "2:1 (3% SL / 6% TP)": (3.0, 6.0),
}

CRON_ANTES_HORAS_UTC = {14, 18, 22}
CRON_ANTES_VENTANA = 3

CRON_DESPUES_HORAS_UTC = {2, 6, 10, 14, 18, 22}
CRON_DESPUES_VENTANA = 6

WARMUP = max(EMA_SLOW_PERIOD + 1, TREND_SMA_PERIOD)


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
    diff = df["ema_fast"] - df["ema_slow"]
    prev_diff = diff.shift(1)
    df["cruce"] = None
    df.loc[(prev_diff < 0) & (diff > 0), "cruce"] = "dorado"
    df.loc[(prev_diff > 0) & (diff < 0), "cruce"] = "muerte"
    return df


def cruces_reales(df: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    """Todos los cruces EMA reales en el histórico (verdad de terreno)."""
    ocurridos = df[df["cruce"].notna()]
    return list(zip(ocurridos.index, ocurridos["cruce"]))


def simular_produccion(df, horas_cron, ventana_velas, con_dedup, sl_pct, tp_pct):
    """Simula el bot corriendo solo en `horas_cron` (UTC), mirando hasta
    `ventana_velas` hacia atrás en busca de un cruce, con o sin dedup por
    timestamp (para reproducir ANTES vs DESPUES).
    """
    trades = []
    cruces_notificados = set()  # timestamps de cruce ya usados (si con_dedup)
    ultimo_cruce_visto = None
    last_exit_idx = -10 ** 9

    checkpoints = [i for i in range(WARMUP, len(df) - 1) if df.index[i].hour in horas_cron]

    for i in checkpoints:
        # La detección de cruces (y su registro en el estado persistido) se
        # evalúa SIEMPRE en cada corrida, igual que en producción - no hay
        # concepto de "cooldown" en analyze_and_notify.py, cada ejecución
        # relee el estado y lo actualiza sin importar si se abrió un trade
        # recientemente. El cooldown de abajo solo controla si esta
        # simulación decide "tomar" el trade, no si el cruce se vio.
        cruce, cruce_ts = None, None
        for k in range(i - ventana_velas + 1, i + 1):
            if k < 0 or pd.isna(df["cruce"].iloc[k]):
                continue
            cruce, cruce_ts = df["cruce"].iloc[k], df.index[k]

        if con_dedup and cruce_ts is not None and cruce_ts == ultimo_cruce_visto:
            cruce = None
        if cruce_ts is not None:
            ultimo_cruce_visto = cruce_ts
            cruces_notificados.add(cruce_ts)

        if i - last_exit_idx < COOLDOWN_HOURS:
            continue

        row = df.iloc[i]
        trend = row["sma_trend"]
        if pd.isna(trend):
            continue

        direccion = None
        if row["close"] > trend and (row["rsi"] < RSI_OVERSOLD or cruce == "dorado"):
            direccion = "LARGO"
        elif row["close"] < trend and (row["rsi"] > RSI_OVERBOUGHT or cruce == "muerte"):
            direccion = "CORTO"
        if direccion is None:
            continue

        entrada = row["close"]
        if direccion == "CORTO":
            sl, tp = entrada * (1 + sl_pct / 100), entrada * (1 - tp_pct / 100)
        else:
            sl, tp = entrada * (1 - sl_pct / 100), entrada * (1 + tp_pct / 100)

        outcome, exit_i = None, None
        for j in range(i + 1, min(i + 1 + MAX_HOLD_HOURS, len(df))):
            hi, lo = df.iloc[j]["high"], df.iloc[j]["low"]
            hit_sl = (hi >= sl) if direccion == "CORTO" else (lo <= sl)
            hit_tp = (lo <= tp) if direccion == "CORTO" else (hi >= tp)
            if hit_sl:
                outcome, exit_i = "SL", j
                break
            if hit_tp:
                outcome, exit_i = "TP", j
                break
        if outcome is None:
            outcome, exit_i = "TIMEOUT", min(i + MAX_HOLD_HOURS, len(df) - 1)

        pnl = tp_pct if outcome == "TP" else (-sl_pct if outcome == "SL" else 0.0)
        trades.append({"direccion": direccion, "resultado": outcome, "pnl_pct": pnl,
                        "entrada_ts": df.index[i], "cruce_usado": cruce,
                        "horas_hasta_salida": exit_i - i})
        last_exit_idx = exit_i

    return pd.DataFrame(trades), cruces_notificados


def resumen(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate_%": 0.0, "pnl_acumulado_%": 0.0,
                "horas_prom_hasta_tp": None}
    ganadores = trades[trades["resultado"] == "TP"]
    total = len(trades)
    horas_prom = ganadores["horas_hasta_salida"].mean() if not ganadores.empty else None
    return {
        "trades": total,
        "win_rate_%": round(len(ganadores) / total * 100, 1),
        "pnl_acumulado_%": round(trades["pnl_pct"].sum(), 1),
        "horas_prom_hasta_tp": round(horas_prom, 1) if horas_prom is not None else None,
    }


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    dfs = {}
    filas_cruces = []

    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = add_indicators(df)
        dfs[symbol] = df

        todos_los_cruces = {ts for ts, _tipo in cruces_reales(df) if ts >= df.index[WARMUP]}
        # con_dedup no cambia qué cruces se ven, solo si generan señal duplicada -
        # se usa cualquier config de SL/TP solo para poblar el set de "vistos"
        _, notificados_antes = simular_produccion(
            df, CRON_ANTES_HORAS_UTC, CRON_ANTES_VENTANA, con_dedup=False, sl_pct=5.0, tp_pct=3.0
        )
        _, notificados_despues = simular_produccion(
            df, CRON_DESPUES_HORAS_UTC, CRON_DESPUES_VENTANA, con_dedup=True, sl_pct=5.0, tp_pct=3.0
        )
        filas_cruces.append({
            "symbol": symbol,
            "cruces_totales": len(todos_los_cruces),
            "perdidos_ANTES": len(todos_los_cruces - notificados_antes),
            "perdidos_DESPUES": len(todos_los_cruces - notificados_despues),
        })

    df_cruces = pd.DataFrame(filas_cruces)
    print("\n" + "=" * 78)
    print("CRUCES EMA REALES vs CRUCES PERDIDOS POR CADA CRON")
    print("=" * 78)
    print(df_cruces.to_string(index=False))
    total_cruces = df_cruces["cruces_totales"].sum()
    print(f"\nTotal cruces reales: {total_cruces}")
    print(f"Perdidos con cron ANTES:   {df_cruces['perdidos_ANTES'].sum()} "
          f"({df_cruces['perdidos_ANTES'].sum() / total_cruces * 100:.1f}%)")
    print(f"Perdidos con cron DESPUES: {df_cruces['perdidos_DESPUES'].sum()} "
          f"({df_cruces['perdidos_DESPUES'].sum() / total_cruces * 100:.1f}%)")
    df_cruces.to_csv("resultados_cron_gaps_cruces.csv", index=False)

    # A partir de acá, solo el cron DESPUES (el que corre en producción),
    # comparando distintos ratios de riesgo/beneficio.
    filas_resumen = []
    for nombre_config, (sl_pct, tp_pct) in CONFIGS_SL_TP.items():
        for symbol, df in dfs.items():
            trades, _ = simular_produccion(
                df, CRON_DESPUES_HORAS_UTC, CRON_DESPUES_VENTANA, con_dedup=True,
                sl_pct=sl_pct, tp_pct=tp_pct,
            )
            filas_resumen.append({"symbol": symbol, "config_sl_tp": nombre_config, **resumen(trades)})

    df_resumen = pd.DataFrame(filas_resumen)

    print("\n" + "=" * 78)
    print("RESULTADO DE TRADING POR RATIO SL/TP (cron DESPUES, todas las monedas)")
    print("=" * 78)
    print(df_resumen.to_string(index=False))

    print("\n" + "-" * 78)
    print("RESUMEN GLOBAL POR RATIO SL/TP")
    print("-" * 78)
    for nombre_config in CONFIGS_SL_TP:
        sub = df_resumen[df_resumen["config_sl_tp"] == nombre_config]
        t = sub["trades"].sum()
        wr = (sub["trades"] * sub["win_rate_%"]).sum() / t if t else 0
        pnl = sub["pnl_acumulado_%"].sum()
        con_tp = sub.dropna(subset=["horas_prom_hasta_tp"])
        horas_prom = (
            (con_tp["horas_prom_hasta_tp"] * con_tp["trades"] * con_tp["win_rate_%"] / 100).sum()
            / (con_tp["trades"] * con_tp["win_rate_%"] / 100).sum()
            if not con_tp.empty else None
        )
        horas_txt = f"{horas_prom:.1f}h (~{horas_prom / 24:.1f} días)" if horas_prom is not None else "N/A"
        print(f"\n{nombre_config} -> Trades: {t} | Win rate ponderado: {wr:.1f}% | "
              f"PnL acumulado: {pnl:.1f}% | Tiempo promedio hasta TP: {horas_txt}")

    df_resumen.to_csv("resultados_cron_gaps_resumen.csv", index=False)
    print("\nGuardado: resultados_cron_gaps_resumen.csv, resultados_cron_gaps_cruces.csv")


if __name__ == "__main__":
    main()
