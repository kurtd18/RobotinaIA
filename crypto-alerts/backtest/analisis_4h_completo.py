"""
Tres análisis sobre velas de 4 HORAS (que además coincide con el
intervalo real del cron de producción, así que acá cada vela = una
corrida real, sin necesidad de filtrar por hora del día), sobre las 4
monedas de producción (XRP, ETH, DOGE, SOL), 730 días:

  1. Precisión del CRUCE EMA12/26 como gatillo (lo que faltaba medir -
     hasta ahora solo se había medido precisión de RSI/MFI/Bollinger).
  2. Precisión del gatillo triple RSI+MFI+Bollinger%B, ahora en las 4
     monedas (no solo XRP) para ver si la mejora se sostiene fuera de
     XRP.
  3. Máxima excursión favorable (MFE) de cada señal de entrada real de
     producción: cuánto % a favor llega a moverse el precio, en
     promedio, ANTES de que la racha se corte - para decidir si el
     take-profit de 3% es realista o si conviene bajarlo a 1.5%.

Uso:
    pip install -r requirements.txt
    python analisis_4h_completo.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd

from analisis_puntos_quiebre_xrp import (
    EXCHANGE_ID, fetch_ohlcv_full, calcular_indicadores,
    detectar_pivotes, filtrar_quiebres_reales,
)
import analisis_puntos_quiebre_xrp as apq

SYMBOLS = ["XRP/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT"]
TIMEFRAME = "4h"
LOOKBACK_DAYS = 730

VENTANA_CONFIRMACION_VELAS = 18   # 72h / 4h
TOLERANCIA_VELAS = 6              # 24h / 4h
CRUCE_VENTANA_VELAS = 6           # "cruce reciente" = últimas 24h

RSI_OVERSOLD, RSI_OVERBOUGHT = 30, 70
MFI_OVERSOLD, MFI_OVERBOUGHT = 20, 80

MAX_HOLD_VELAS = 14 * 24 // 4     # 14 días en velas de 4h


def agregar_mfi_bollinger(df: pd.DataFrame) -> pd.DataFrame:
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    precio_tipico = (high + low + close) / 3
    flujo_dinero = precio_tipico * volume
    direccion = precio_tipico.diff()
    flujo_positivo = flujo_dinero.where(direccion > 0, 0.0).rolling(14).sum()
    flujo_negativo = flujo_dinero.where(direccion < 0, 0.0).rolling(14).sum()
    df["mfi14"] = 100 - (100 / (1 + flujo_positivo / flujo_negativo))

    sma20, std20 = close.rolling(20).mean(), close.rolling(20).std()
    bb_lower, bb_upper = sma20 - 2 * std20, sma20 + 2 * std20
    df["bb_pct_b"] = (close - bb_lower) / (bb_upper - bb_lower)
    return df


def marcar_cercania(n: int, idxs: list[int], tolerancia: int) -> np.ndarray:
    cercania = np.zeros(n, dtype=bool)
    for idx in idxs:
        ini, fin = max(0, idx - tolerancia), min(n, idx + tolerancia + 1)
        cercania[ini:fin] = True
    return cercania


def evaluar_precision_global(series_por_symbol: dict, cercania_por_symbol: dict, warmup: int) -> dict:
    """Junta todas las monedas en un solo cálculo de precisión (pool
    conjunto), para tener una muestra más grande y menos ruidosa que
    evaluar cada moneda por separado."""
    todas_activas, todas_cercania = [], []
    for symbol, serie in series_por_symbol.items():
        rango = slice(warmup, len(serie) - 1)
        todas_activas.append(serie.iloc[rango].fillna(False).values.astype(bool))
        todas_cercania.append(cercania_por_symbol[symbol][rango])

    activas = np.concatenate(todas_activas)
    cercania = np.concatenate(todas_cercania)

    total = int(activas.sum())
    if total == 0:
        return {"veces_activada": 0, "precisión_%": None, "lift_vs_azar": None}

    aciertos = int((activas & cercania).sum())
    base = cercania.mean() * 100
    precision = aciertos / total * 100
    return {
        "veces_activada": total,
        "%_del_tiempo_activa": round(total / len(activas) * 100, 1),
        "precisión_%": round(precision, 1),
        "falsos_positivos_%": round(100 - precision, 1),
        "lift_vs_azar": round(precision / base, 2) if base > 0 else None,
    }


def generar_senales_produccion(df: pd.DataFrame, warmup: int) -> list[dict]:
    """Regla de producción (SMA200 + RSI/cruce), evaluada en cada vela de
    4h (ya coincide con el cron real). Devuelve señales con su índice para
    poder medir después la excursión favorable."""
    senales = []
    ultimo_cruce_visto = None

    for i in range(warmup, len(df) - 1):
        cruce, cruce_ts = None, None
        for k in range(max(0, i - CRUCE_VENTANA_VELAS + 1), i + 1):
            if pd.isna(df["cruce_ema"].iloc[k]):
                continue
            cruce, cruce_ts = df["cruce_ema"].iloc[k], df.index[k]

        if cruce_ts is not None and cruce_ts == ultimo_cruce_visto:
            cruce = None
        if cruce_ts is not None:
            ultimo_cruce_visto = cruce_ts

        row = df.iloc[i]
        if pd.isna(row["sma200"]):
            continue

        direccion = None
        if row["close"] > row["sma200"] and (row["rsi14"] < RSI_OVERSOLD or cruce == "dorado"):
            direccion = "LARGO"
        elif row["close"] < row["sma200"] and (row["rsi14"] > RSI_OVERBOUGHT or cruce == "muerte"):
            direccion = "CORTO"

        if direccion:
            senales.append({"idx": i, "direccion": direccion})

    return senales


def medir_mfe(df: pd.DataFrame, senales: list[dict]) -> list[float]:
    """Para cada señal, la máxima excursión favorable (%) alcanzada en
    cualquier punto dentro de MAX_HOLD_VELAS, antes de que se acabe la
    ventana - independiente de cualquier SL/TP fijo."""
    mfes = []
    precio = df["close"].values
    high, low = df["high"].values, df["low"].values

    for s in senales:
        i = s["idx"]
        limite = min(i + MAX_HOLD_VELAS, len(df) - 1)
        entrada = precio[i]
        if limite <= i:
            continue
        if s["direccion"] == "LARGO":
            mejor = high[i + 1:limite + 1].max()
            mfe = (mejor - entrada) / entrada * 100
        else:
            peor = low[i + 1:limite + 1].min()
            mfe = (entrada - peor) / entrada * 100
        mfes.append(mfe)

    return mfes


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    apq.VENTANA_CONFIRMACION_HORAS = VENTANA_CONFIRMACION_VELAS

    warmup = 200
    dfs = {}
    cercania_largo, cercania_corto = {}, {}
    todas_senales_produccion = {}

    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ({TIMEFRAME}) ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = calcular_indicadores(df)
        df = agregar_mfi_bollinger(df)
        dfs[symbol] = df

        pivotes = detectar_pivotes(df)
        quiebres = filtrar_quiebres_reales(df, pivotes)
        largos = [q for q in quiebres if q["direccion"] == "LARGO"]
        cortos = [q for q in quiebres if q["direccion"] == "CORTO"]
        print(f"  {len(largos)} quiebres LARGO, {len(cortos)} quiebres CORTO confirmados")

        cercania_largo[symbol] = marcar_cercania(len(df), [q["idx"] for q in largos], TOLERANCIA_VELAS)
        cercania_corto[symbol] = marcar_cercania(len(df), [q["idx"] for q in cortos], TOLERANCIA_VELAS)

        todas_senales_produccion[symbol] = generar_senales_produccion(df, warmup)

    # --- 1 y 2: precisión de gatillos, agrupando las 4 monedas ---
    condiciones_largo = {
        "RSI < 30 (solo)": lambda df: df["rsi14"] < 30,
        "MFI < 20 (solo)": lambda df: df["mfi14"] < 20,
        "Bollinger %B < 0 (solo)": lambda df: df["bb_pct_b"] < 0,
        "RSI+MFI+Bollinger (triple)": lambda df: (df["rsi14"] < 30) & (df["mfi14"] < 20) & (df["bb_pct_b"] < 0),
        "Cruce EMA dorado (últimas 24h)": lambda df: pd.concat(
            [(df["cruce_ema"] == "dorado").shift(k).fillna(False) for k in range(CRUCE_VENTANA_VELAS)], axis=1
        ).any(axis=1),
    }
    condiciones_corto = {
        "RSI > 70 (solo)": lambda df: df["rsi14"] > 70,
        "MFI > 80 (solo)": lambda df: df["mfi14"] > 80,
        "Bollinger %B > 1 (solo)": lambda df: df["bb_pct_b"] > 1,
        "RSI+MFI+Bollinger (triple)": lambda df: (df["rsi14"] > 70) & (df["mfi14"] > 80) & (df["bb_pct_b"] > 1),
        "Cruce EMA muerte (últimas 24h)": lambda df: pd.concat(
            [(df["cruce_ema"] == "muerte").shift(k).fillna(False) for k in range(CRUCE_VENTANA_VELAS)], axis=1
        ).any(axis=1),
    }

    print("\n" + "=" * 100)
    print(f"PRECISIÓN DE GATILLOS - LARGO (4 monedas juntas, velas {TIMEFRAME})")
    print("=" * 100)
    filas = []
    for nombre, fn in condiciones_largo.items():
        series = {s: fn(dfs[s]) for s in SYMBOLS}
        r = evaluar_precision_global(series, cercania_largo, warmup)
        filas.append({"condición": nombre, **r})
    df_largo = pd.DataFrame(filas).sort_values("precisión_%", ascending=False, na_position="last")
    print(df_largo.to_string(index=False))
    df_largo.to_csv("resultados_precision_4h_largo_todas_monedas.csv", index=False)

    print("\n" + "=" * 100)
    print(f"PRECISIÓN DE GATILLOS - CORTO (4 monedas juntas, velas {TIMEFRAME})")
    print("=" * 100)
    filas = []
    for nombre, fn in condiciones_corto.items():
        series = {s: fn(dfs[s]) for s in SYMBOLS}
        r = evaluar_precision_global(series, cercania_corto, warmup)
        filas.append({"condición": nombre, **r})
    df_corto = pd.DataFrame(filas).sort_values("precisión_%", ascending=False, na_position="last")
    print(df_corto.to_string(index=False))
    df_corto.to_csv("resultados_precision_4h_corto_todas_monedas.csv", index=False)

    # --- 3: MFE de las señales reales de producción ---
    print("\n" + "=" * 100)
    print("MÁXIMA EXCURSIÓN FAVORABLE (MFE) DE LAS SEÑALES DE PRODUCCIÓN (4h, 4 monedas)")
    print("=" * 100)
    todos_mfe = []
    for symbol in SYMBOLS:
        mfes = medir_mfe(dfs[symbol], todas_senales_produccion[symbol])
        todos_mfe.extend(mfes)
        if mfes:
            serie = pd.Series(mfes)
            print(f"{symbol}: {len(mfes)} señales | media {serie.mean():.2f}% | mediana {serie.median():.2f}% | "
                  f">=1.5%: {(serie >= 1.5).mean() * 100:.1f}% | >=3%: {(serie >= 3).mean() * 100:.1f}% | "
                  f">=5%: {(serie >= 5).mean() * 100:.1f}%")

    serie_total = pd.Series(todos_mfe)
    print(f"\nTOTAL ({len(todos_mfe)} señales, 4 monedas):")
    print(f"  Media: {serie_total.mean():.2f}%  |  Mediana: {serie_total.median():.2f}%")
    print(f"  Percentil 25: {serie_total.quantile(0.25):.2f}%  |  Percentil 75: {serie_total.quantile(0.75):.2f}%")
    print(f"  % de señales que alcanzan >=1.5%: {(serie_total >= 1.5).mean() * 100:.1f}%")
    print(f"  % de señales que alcanzan >=3.0%: {(serie_total >= 3.0).mean() * 100:.1f}%")
    print(f"  % de señales que alcanzan >=5.0%: {(serie_total >= 5.0).mean() * 100:.1f}%")
    serie_total.to_csv("resultados_mfe_senales_produccion_4h.csv", index=False, header=["mfe_%"])


if __name__ == "__main__":
    main()
