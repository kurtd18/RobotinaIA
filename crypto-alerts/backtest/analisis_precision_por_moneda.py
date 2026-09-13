"""
Mide la precisión del gatillo de entrada NO agrupada (como en
analisis_4h_completo.py, que junta las 15 monedas en un solo cálculo)
sino MONEDA POR MONEDA, para las 15 monedas del universo ampliado.

Motivo: el backtest de portafolio con las 15 monedas empeoró el
resultado (65.7% -> 62.7% win rate) respecto a las 4 originales -
la sospecha es que el filtro (validado solo en XRP/ETH/DOGE/SOL) no
funciona igual de bien en las 11 monedas nuevas. Esto lo confirma o
lo descarta, y arma una lista de "universo seleccionado" con solo las
monedas donde el gatillo tiene precisión reasonable.

Gatillos evaluados (igual que en producción tras los cambios anteriores):
  - LARGO: RSI<30 Y MFI<20 Y Bollinger%B<0 (el "triple")
  - CORTO: RSI>70 solo (el triple no ayudó de ese lado)

Uso:
    pip install -r requirements.txt
    python analisis_precision_por_moneda.py
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
from backtest_cron_gaps import SYMBOLS

TIMEFRAME = "4h"
LOOKBACK_DAYS = 730
VENTANA_CONFIRMACION_VELAS = 18   # 72h / 4h
TOLERANCIA_VELAS = 6              # 24h / 4h
WARMUP = 200

# Umbrales mínimos para considerar una moneda "apta" para el universo
# seleccionado: la precisión del gatillo debe superar claramente el azar
# (lift) y no basarse en un puñado de activaciones poco confiables.
LIFT_MINIMO = 1.3
ACTIVACIONES_MINIMAS = 15


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


def precision_condicion(serie_bool: pd.Series, cercania: np.ndarray, warmup: int) -> dict:
    rango = slice(warmup, len(serie_bool) - 1)
    activa = serie_bool.iloc[rango].fillna(False).values.astype(bool)
    total = int(activa.sum())
    base = cercania[rango].mean() * 100
    if total == 0:
        return {"veces_activada": 0, "precisión_%": None, "lift_vs_azar": None}
    aciertos = int((activa & cercania[rango]).sum())
    precision = aciertos / total * 100
    return {
        "veces_activada": total,
        "precisión_%": round(precision, 1),
        "lift_vs_azar": round(precision / base, 2) if base > 0 else None,
    }


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    apq.VENTANA_CONFIRMACION_HORAS = VENTANA_CONFIRMACION_VELAS

    filas = []
    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = calcular_indicadores(df)
        df = agregar_mfi_bollinger(df)

        pivotes = detectar_pivotes(df)
        quiebres = filtrar_quiebres_reales(df, pivotes)
        largos = [q for q in quiebres if q["direccion"] == "LARGO"]
        cortos = [q for q in quiebres if q["direccion"] == "CORTO"]

        cercania_largo = marcar_cercania(len(df), [q["idx"] for q in largos], TOLERANCIA_VELAS)
        cercania_corto = marcar_cercania(len(df), [q["idx"] for q in cortos], TOLERANCIA_VELAS)

        triple_largo = (df["rsi14"] < 30) & (df["mfi14"] < 20) & (df["bb_pct_b"] < 0)
        rsi_corto = df["rsi14"] > 70

        r_largo = precision_condicion(triple_largo, cercania_largo, WARMUP)
        r_corto = precision_condicion(rsi_corto, cercania_corto, WARMUP)

        filas.append({
            "symbol": symbol,
            "quiebres_largo": len(largos), "quiebres_corto": len(cortos),
            "activaciones_triple_largo": r_largo["veces_activada"],
            "precisión_largo_%": r_largo["precisión_%"], "lift_largo": r_largo["lift_vs_azar"],
            "activaciones_rsi_corto": r_corto["veces_activada"],
            "precisión_corto_%": r_corto["precisión_%"], "lift_corto": r_corto["lift_vs_azar"],
        })

    df_resultado = pd.DataFrame(filas)
    print("\n" + "=" * 110)
    print("PRECISIÓN DEL GATILLO POR MONEDA (LARGO: triple RSI+MFI+BB | CORTO: RSI solo)")
    print("=" * 110)
    print(df_resultado.to_string(index=False))
    df_resultado.to_csv("resultados_precision_por_moneda.csv", index=False)

    seleccionadas = df_resultado[
        (df_resultado["lift_largo"].fillna(0) >= LIFT_MINIMO) &
        (df_resultado["activaciones_triple_largo"].fillna(0) >= ACTIVACIONES_MINIMAS)
    ]["symbol"].tolist()

    print("\n" + "-" * 110)
    print(f"UNIVERSO SELECCIONADO (lift LARGO >= {LIFT_MINIMO} y >= {ACTIVACIONES_MINIMAS} activaciones)")
    print("-" * 110)
    print(seleccionadas if seleccionadas else "Ninguna moneda cumple el criterio")


if __name__ == "__main__":
    main()
