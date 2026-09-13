"""
Complemento de analisis_puntos_quiebre_xrp.py: esa parte 1 midió RECALL
("de los quiebres reales, qué % tenía cada condición activa"). Acá se mide
la otra mitad de la historia - PRECISIÓN / falsos positivos: "de todas las
veces que la condición se activó, qué % realmente estuvo cerca de un
quiebre real" (y qué % fue una falsa alarma).

Un indicador puede tener recall alto y ser igual inútil como gatillo si
también se dispara todo el tiempo sin que pase nada (baja precisión).

Metodología:
  - Se reutilizan los mismos 326 puntos de quiebre confirmados (163 LARGO,
    163 CORTO) de analisis_puntos_quiebre_xrp.py.
  - Para cada vela del histórico (no solo los quiebres), se marca si esa
    vela está "cerca" (± TOLERANCIA_HORAS) de un quiebre real de LARGO o
    de CORTO.
  - Para cada condición de indicador, se calcula:
      precisión = (veces que se activó Y estaba cerca de un quiebre real)
                  / (veces que se activó, en total)
      tasa de falsos positivos = 1 - precisión
      lift = precisión / tasa base (qué tan mejor es la condición que
             "adivinar al azar" en qué vela estás cerca de un quiebre)

Uso:
    pip install -r requirements.txt
    python analisis_falsos_positivos_xrp.py
"""

import numpy as np
import pandas as pd

from analisis_puntos_quiebre_xrp import (
    SYMBOL, EXCHANGE_ID, TIMEFRAME, LOOKBACK_DAYS,
    fetch_ohlcv_full, calcular_indicadores, detectar_pivotes, filtrar_quiebres_reales,
)
import ccxt
from datetime import datetime, timedelta, timezone

TOLERANCIA_HORAS = 24

# Condiciones candidatas a "gatillo de entrada" para LARGO (todas leen como
# "sobreventa/extremo bajista puntual", no como "tendencia bajista en curso" -
# esas últimas casi siempre están activas en cualquier tramo bajista y por
# eso no sirven como gatillo puntual, solo como contexto).
CONDICIONES_LARGO = {
    "RSI < 30": lambda df: df["rsi14"] < 30,
    "Estocástico < 20": lambda df: df["stoch_k"] < 20,
    "CCI < -100": lambda df: df["cci20"] < -100,
    "Williams %R < -80": lambda df: df["willr14"] < -80,
    "MFI < 20": lambda df: df["mfi14"] < 20,
    "Bollinger %B < 0": lambda df: df["bb_pct_b"] < 0,
    "Volumen > 1.5x promedio": lambda df: df["vol_ratio"] > 1.5,
    "Volumen > 2x promedio": lambda df: df["vol_ratio"] > 2.0,
    "Cruce EMA12/26 dorado (últimas 6 velas)": lambda df: pd.concat(
        [(df["cruce_ema"] == "dorado").shift(k).fillna(False) for k in range(6)], axis=1).any(axis=1),
}

CONDICIONES_CORTO = {
    "RSI > 70": lambda df: df["rsi14"] > 70,
    "Estocástico > 80": lambda df: df["stoch_k"] > 80,
    "CCI > 100": lambda df: df["cci20"] > 100,
    "Williams %R > -20": lambda df: df["willr14"] > -20,
    "MFI > 80": lambda df: df["mfi14"] > 80,
    "Bollinger %B > 1": lambda df: df["bb_pct_b"] > 1,
    "Volumen > 1.5x promedio": lambda df: df["vol_ratio"] > 1.5,
    "Volumen > 2x promedio": lambda df: df["vol_ratio"] > 2.0,
    "Cruce EMA12/26 muerte (últimas 6 velas)": lambda df: pd.concat(
        [(df["cruce_ema"] == "muerte").shift(k).fillna(False) for k in range(6)], axis=1).any(axis=1),
}


def marcar_cercania(n: int, idxs_quiebre: list[int], tolerancia: int) -> np.ndarray:
    cercania = np.zeros(n, dtype=bool)
    for idx in idxs_quiebre:
        ini, fin = max(0, idx - tolerancia), min(n, idx + tolerancia + 1)
        cercania[ini:fin] = True
    return cercania


def evaluar_precision(df: pd.DataFrame, condiciones: dict, cercania: np.ndarray, warmup: int) -> pd.DataFrame:
    rango = slice(warmup, len(df) - 1)
    base_rate = cercania[rango].mean() * 100

    filas = []
    for nombre, fn in condiciones.items():
        serie = fn(df).iloc[rango].fillna(False).values.astype(bool)
        total_activaciones = serie.sum()
        if total_activaciones == 0:
            continue
        aciertos = (serie & cercania[rango]).sum()
        precision = aciertos / total_activaciones * 100
        filas.append({
            "condición": nombre,
            "veces_activada": int(total_activaciones),
            "%_del_tiempo_activa": round(total_activaciones / (rango.stop - rango.start) * 100, 1),
            "precisión_%": round(precision, 1),
            "falsos_positivos_%": round(100 - precision, 1),
            "lift_vs_azar": round(precision / base_rate, 2) if base_rate > 0 else None,
        })

    df_resultado = pd.DataFrame(filas).sort_values("precisión_%", ascending=False)
    return df_resultado, base_rate


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    print(f"Descargando {SYMBOL} {TIMEFRAME}, {LOOKBACK_DAYS} días...")
    df = fetch_ohlcv_full(exchange, SYMBOL, TIMEFRAME, since_ms)
    df = calcular_indicadores(df)

    pivotes = detectar_pivotes(df)
    quiebres = filtrar_quiebres_reales(df, pivotes)
    largos = [q for q in quiebres if q["direccion"] == "LARGO"]
    cortos = [q for q in quiebres if q["direccion"] == "CORTO"]
    print(f"{len(largos)} quiebres LARGO, {len(cortos)} quiebres CORTO confirmados")

    warmup = 200  # SMA200 necesita 200 velas de historia
    n = len(df)

    cercania_largo = marcar_cercania(n, [q["idx"] for q in largos], TOLERANCIA_HORAS)
    cercania_corto = marcar_cercania(n, [q["idx"] for q in cortos], TOLERANCIA_HORAS)

    print(f"\nTolerancia de cercanía: ±{TOLERANCIA_HORAS}h alrededor de cada quiebre real")

    print("\n" + "=" * 100)
    print("PRECISIÓN / FALSOS POSITIVOS - CONDICIONES CANDIDATAS A GATILLO DE LARGO")
    print("=" * 100)
    df_largo, base_largo = evaluar_precision(df, CONDICIONES_LARGO, cercania_largo, warmup)
    print(f"Tasa base (una vela cualquiera está cerca de un quiebre LARGO real): {base_largo:.1f}%")
    print(df_largo.to_string(index=False))
    df_largo.to_csv("resultados_precision_gatillos_largo_xrp.csv", index=False)

    print("\n" + "=" * 100)
    print("PRECISIÓN / FALSOS POSITIVOS - CONDICIONES CANDIDATAS A GATILLO DE CORTO")
    print("=" * 100)
    df_corto, base_corto = evaluar_precision(df, CONDICIONES_CORTO, cercania_corto, warmup)
    print(f"Tasa base (una vela cualquiera está cerca de un quiebre CORTO real): {base_corto:.1f}%")
    print(df_corto.to_string(index=False))
    df_corto.to_csv("resultados_precision_gatillos_corto_xrp.csv", index=False)


if __name__ == "__main__":
    main()
