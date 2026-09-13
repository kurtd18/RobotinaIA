"""
Extiende analisis_falsos_positivos_xrp.py en dos direcciones:

  1. Prueba COMBINACIONES de condiciones (RSI+MFI, RSI+Bollinger %B,
     RSI+MFI+Bollinger %B) para ver si la precisión sube por encima del
     RSI solo (50.4% LARGO / 61.4% CORTO, ver resultados_precision_
     gatillos_*_xrp.csv) al exigir que varias señales coincidan.
  2. Repite todo el análisis en velas de 1 DÍA además de 1 hora, para ver
     si el patrón se sostiene en otro timeframe o es particular de 1h.

Uso:
    pip install -r requirements.txt
    python analisis_combinaciones_xrp.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd

from analisis_puntos_quiebre_xrp import (
    SYMBOL, EXCHANGE_ID, fetch_ohlcv_full, calcular_indicadores,
    detectar_pivotes, filtrar_quiebres_reales,
)
import analisis_puntos_quiebre_xrp as apq

LOOKBACK_DAYS = 730

# Config por timeframe: cuántas velas equivalen a la "ventana de
# confirmación" (72h) y a la "tolerancia de cercanía" (24h) usadas en los
# análisis anteriores de 1h, para que sigan representando ~3 días y ~1 día
# reales sin importar el timeframe.
CONFIG_TIMEFRAME = {
    "1h": {"ventana_confirmacion_velas": 72, "tolerancia_velas": 24},
    "1d": {"ventana_confirmacion_velas": 3, "tolerancia_velas": 1},
}


def marcar_cercania(n: int, idxs_quiebre: list[int], tolerancia: int) -> np.ndarray:
    cercania = np.zeros(n, dtype=bool)
    for idx in idxs_quiebre:
        ini, fin = max(0, idx - tolerancia), min(n, idx + tolerancia + 1)
        cercania[ini:fin] = True
    return cercania


CONDICIONES_LARGO = {
    "RSI < 30 (solo)": lambda df: df["rsi14"] < 30,
    "MFI < 20 (solo)": lambda df: df["mfi14"] < 20,
    "Bollinger %B < 0 (solo)": lambda df: df["bb_pct_b"] < 0,
    "RSI < 30 Y MFI < 20": lambda df: (df["rsi14"] < 30) & (df["mfi14"] < 20),
    "RSI < 30 Y Bollinger %B < 0": lambda df: (df["rsi14"] < 30) & (df["bb_pct_b"] < 0),
    "MFI < 20 Y Bollinger %B < 0": lambda df: (df["mfi14"] < 20) & (df["bb_pct_b"] < 0),
    "RSI < 30 Y MFI < 20 Y Bollinger %B < 0": lambda df: (df["rsi14"] < 30) & (df["mfi14"] < 20) & (df["bb_pct_b"] < 0),
    "RSI < 30 O MFI < 20 (unión)": lambda df: (df["rsi14"] < 30) | (df["mfi14"] < 20),
}

CONDICIONES_CORTO = {
    "RSI > 70 (solo)": lambda df: df["rsi14"] > 70,
    "MFI > 80 (solo)": lambda df: df["mfi14"] > 80,
    "Bollinger %B > 1 (solo)": lambda df: df["bb_pct_b"] > 1,
    "RSI > 70 Y MFI > 80": lambda df: (df["rsi14"] > 70) & (df["mfi14"] > 80),
    "RSI > 70 Y Bollinger %B > 1": lambda df: (df["rsi14"] > 70) & (df["bb_pct_b"] > 1),
    "MFI > 80 Y Bollinger %B > 1": lambda df: (df["mfi14"] > 80) & (df["bb_pct_b"] > 1),
    "RSI > 70 Y MFI > 80 Y Bollinger %B > 1": lambda df: (df["rsi14"] > 70) & (df["mfi14"] > 80) & (df["bb_pct_b"] > 1),
    "RSI > 70 O MFI > 80 (unión)": lambda df: (df["rsi14"] > 70) | (df["mfi14"] > 80),
}


def evaluar_precision(df: pd.DataFrame, condiciones: dict, cercania: np.ndarray, warmup: int) -> pd.DataFrame:
    rango = slice(warmup, len(df) - 1)
    base_rate = cercania[rango].mean() * 100

    filas = []
    for nombre, fn in condiciones.items():
        serie = fn(df).iloc[rango].fillna(False).values.astype(bool)
        total_activaciones = int(serie.sum())
        if total_activaciones == 0:
            filas.append({"condición": nombre, "veces_activada": 0, "%_del_tiempo_activa": 0.0,
                          "precisión_%": None, "falsos_positivos_%": None, "lift_vs_azar": None})
            continue
        aciertos = int((serie & cercania[rango]).sum())
        precision = aciertos / total_activaciones * 100
        filas.append({
            "condición": nombre,
            "veces_activada": total_activaciones,
            "%_del_tiempo_activa": round(total_activaciones / (rango.stop - rango.start) * 100, 1),
            "precisión_%": round(precision, 1),
            "falsos_positivos_%": round(100 - precision, 1),
            "lift_vs_azar": round(precision / base_rate, 2) if base_rate > 0 else None,
        })

    return pd.DataFrame(filas), base_rate


def analizar_timeframe(exchange, timeframe: str):
    cfg = CONFIG_TIMEFRAME[timeframe]
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    print(f"\n{'#' * 100}\n# TIMEFRAME {timeframe}\n{'#' * 100}")
    print(f"Descargando {SYMBOL} {timeframe}, {LOOKBACK_DAYS} días...")
    df = fetch_ohlcv_full(exchange, SYMBOL, timeframe, since_ms)
    print(f"{len(df)} velas descargadas ({df.index[0]} -> {df.index[-1]})")
    df = calcular_indicadores(df)

    # Los umbrales de precio (UMBRAL_PIVOTE_PCT, GANANCIA_MINIMA_PCT) del
    # módulo importado se mantienen iguales entre timeframes para que la
    # comparación sea justa - solo cambian las ventanas medidas en velas.
    apq.VENTANA_CONFIRMACION_HORAS = cfg["ventana_confirmacion_velas"]

    pivotes = detectar_pivotes(df)
    quiebres = filtrar_quiebres_reales(df, pivotes)
    largos = [q for q in quiebres if q["direccion"] == "LARGO"]
    cortos = [q for q in quiebres if q["direccion"] == "CORTO"]
    print(f"{len(largos)} quiebres LARGO, {len(cortos)} quiebres CORTO confirmados "
          f"(ganancia >= {apq.GANANCIA_MINIMA_PCT}% en <= {cfg['ventana_confirmacion_velas']} velas)")

    if len(largos) < 5 or len(cortos) < 5:
        print("Muy pocos quiebres confirmados en este timeframe para sacar conclusiones estadísticas fiables.")

    warmup = 200
    n = len(df)
    tol = cfg["tolerancia_velas"]

    cercania_largo = marcar_cercania(n, [q["idx"] for q in largos], tol)
    cercania_corto = marcar_cercania(n, [q["idx"] for q in cortos], tol)

    print(f"\nTolerancia de cercanía: ±{tol} vela(s) ({timeframe})")

    df_largo, base_largo = evaluar_precision(df, CONDICIONES_LARGO, cercania_largo, warmup)
    df_largo = df_largo.sort_values("precisión_%", ascending=False, na_position="last")
    print(f"\n--- CONDICIONES DE LARGO (base = {base_largo:.1f}%) ---")
    print(df_largo.to_string(index=False))
    df_largo.to_csv(f"resultados_combinaciones_largo_xrp_{timeframe}.csv", index=False)

    df_corto, base_corto = evaluar_precision(df, CONDICIONES_CORTO, cercania_corto, warmup)
    df_corto = df_corto.sort_values("precisión_%", ascending=False, na_position="last")
    print(f"\n--- CONDICIONES DE CORTO (base = {base_corto:.1f}%) ---")
    print(df_corto.to_string(index=False))
    df_corto.to_csv(f"resultados_combinaciones_corto_xrp_{timeframe}.csv", index=False)


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    for timeframe in ["1h", "1d"]:
        analizar_timeframe(exchange, timeframe)


if __name__ == "__main__":
    main()
