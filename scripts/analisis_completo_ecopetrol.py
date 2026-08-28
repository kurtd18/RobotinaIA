"""
Análisis completo enfocado SOLO en ECOPETROL.CL: prueba las 13 señales que
hemos construido en total (el score combinado, los 8 criterios
individuales, y las 4 estrategias institucionales) con la misma
metodología rigurosa (sin look-ahead, horizonte de 3 días reales, grupo
de control aleatorio), para encontrar cuál tiene la señal de entrada más
fuerte específicamente en esta acción.

Al final, toma la señal ganadora y afina el objetivo/stop con un barrido
+ validación fuera de muestra, igual que hicimos antes con el score
combinado.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_completo_ecopetrol.py
    python scripts/analisis_completo_ecopetrol.py --dias 59
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas_ta as ta
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.indicators.technical_indicators import agregar_todos_los_indicadores
from scoring import calcular_score, _mayor_que, _atr_relativo, ATR_PCT_THRESHOLD

TZ_BOGOTA = ZoneInfo("America/Bogota")
SYMBOL = "ECOPETROL.CL"

MIN_VELAS = 110
HORIZONTE_TIEMPO = timedelta(days=3)
MAX_VELAS_ABS = 900
PASO_VELAS = 3

OBJETIVO_PCT = 0.03  # regla C, la que mejor separó del azar en pruebas anteriores
STOP_PCT = 0.02

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

GRID_OBJETIVO = [0.015, 0.02, 0.025, 0.03, 0.04]
GRID_STOP = [0.01, 0.015, 0.02, 0.025, 0.03]
MIN_SENALES_CALIBRACION = 5


# --------------------------------------------------------------------------
# Estrategias institucionales (mismas funciones ya probadas antes)
# --------------------------------------------------------------------------

def _pd_isna(valor):
    try:
        return valor != valor
    except Exception:
        return valor is None


def _evaluar_trend_continuation(data_hasta_aqui):
    if len(data_hasta_aqui) < 55:
        return False
    ema20 = ta.ema(data_hasta_aqui["Close"], length=20)
    ema50 = ta.ema(data_hasta_aqui["Close"], length=50)
    vwap = ta.vwap(data_hasta_aqui["High"], data_hasta_aqui["Low"],
                    data_hasta_aqui["Close"], data_hasta_aqui["Volume"])
    if ema20 is None or ema50 is None or vwap is None:
        return False
    u_ema20, u_ema50 = ema20.iloc[-1], ema50.iloc[-1]
    u_close = data_hasta_aqui["Close"].iloc[-1]
    u_vwap = vwap.iloc[-1]
    if any(_pd_isna(v) for v in (u_ema20, u_ema50, u_close, u_vwap)):
        return False
    tendencia = u_ema20 > u_ema50
    sobre_vwap = u_close > u_vwap
    ultimas5_low = data_hasta_aqui["Low"].iloc[-5:]
    ema20_ultimas5 = ema20.iloc[-5:]
    pullback = bool((ultimas5_low.values <= ema20_ultimas5.values).any())
    rebote = u_close > u_ema20
    vol_creciente = data_hasta_aqui["Volume"].iloc[-1] > data_hasta_aqui["Volume"].iloc[-2]
    return bool(tendencia and sobre_vwap and pullback and rebote and vol_creciente)


def _evaluar_liquidity_sweep(data_hasta_aqui, ventana=20):
    if len(data_hasta_aqui) < ventana + 2:
        return False
    anteriores = data_hasta_aqui.iloc[-(ventana + 1):-1]
    minimo = anteriores["Low"].min()
    ultima = data_hasta_aqui.iloc[-1]
    return bool(ultima["Low"] < minimo and ultima["Close"] > minimo)


def _evaluar_volume_profile(data_hasta_aqui, ventana=100, n_bins=20):
    if len(data_hasta_aqui) < ventana + 2:
        return False
    v = data_hasta_aqui.iloc[-ventana:]
    pmin, pmax = v["Low"].min(), v["High"].max()
    if pmax <= pmin:
        return False
    bins = np.linspace(pmin, pmax, n_bins + 1)
    idx_bin = np.clip(np.digitize(v["Close"], bins) - 1, 0, n_bins - 1)
    vol_bin = np.zeros(n_bins)
    for i, vol in zip(idx_bin, v["Volume"]):
        vol_bin[i] += vol
    poc_bin = int(np.argmax(vol_bin))
    poc_precio = (bins[poc_bin] + bins[poc_bin + 1]) / 2
    return bool(data_hasta_aqui["Close"].iloc[-1] > poc_precio)


def _evaluar_market_profile(data_hasta_aqui, ventana=100, n_bins=20):
    if len(data_hasta_aqui) < ventana + 2:
        return False
    v = data_hasta_aqui.iloc[-ventana:]
    pmin, pmax = v["Low"].min(), v["High"].max()
    if pmax <= pmin:
        return False
    bins = np.linspace(pmin, pmax, n_bins + 1)
    idx_bin = np.clip(np.digitize(v["Close"], bins) - 1, 0, n_bins - 1)
    tiempo_bin = np.zeros(n_bins)
    for i in idx_bin:
        tiempo_bin[i] += 1
    orden = np.argsort(tiempo_bin)[::-1]
    total = tiempo_bin.sum()
    acumulado, bins_va = 0, []
    for i in orden:
        acumulado += tiempo_bin[i]
        bins_va.append(i)
        if acumulado >= total * 0.70:
            break
    vah_bin = max(bins_va)
    vah_precio = bins[vah_bin + 1]
    return bool(data_hasta_aqui["Close"].iloc[-1] > vah_precio)


# --------------------------------------------------------------------------
# Las 8 condiciones individuales del score (mismas de scoring.py)
# --------------------------------------------------------------------------

def _evaluar_criterios_individuales(ultimo):
    atr_pct = _atr_relativo(ultimo["ATR"], ultimo["Close"])
    return {
        "RSI": _mayor_que(ultimo["RSI"], 50),
        "EMA": _mayor_que(ultimo["EMA9"], ultimo["EMA21"]),
        "VWAP": _mayor_que(ultimo["Close"], ultimo["VWAP"]),
        "MACD": _mayor_que(ultimo["MACD_12_26_9"], ultimo["MACDs_12_26_9"]),
        "Volumen": _mayor_que(ultimo["Volume"], ultimo["VOL_AVG"]),
        "ATR": _mayor_que(atr_pct, ATR_PCT_THRESHOLD),
        "Momentum": _mayor_que(ultimo["MOM14"], 0),
        "Bollinger": _mayor_que(ultimo["Close"], ultimo["BBU_20_2.0_2.0"]),
    }


SENALES = (
    ["ScoreCombinado"]
    + ["RSI", "EMA", "VWAP", "MACD", "Volumen", "ATR", "Momentum", "Bollinger"]
    + ["TrendContinuation", "LiquiditySweep", "VolumeProfile", "MarketProfile"]
)


@dataclass
class Entrada:
    idx: int
    entrada_ts: object
    entrada_precio: float


def _cargar_datos(dias):
    data = yf.Ticker(SYMBOL).history(period=f"{dias}d", interval="5m")
    if data.empty:
        return None
    data.index = data.index.tz_convert(TZ_BOGOTA)
    return data


def _simular_resultado(data, idx_entrada, precio_entrada, objetivo_pct=OBJETIVO_PCT, stop_pct=STOP_PCT):
    objetivo = precio_entrada * (1 + objetivo_pct)
    stop = precio_entrada * (1 - stop_pct)
    ts_entrada = data.index[idx_entrada]
    fin = min(idx_entrada + MAX_VELAS_ABS, len(data))

    for i in range(idx_entrada + 1, fin):
        if data.index[i] - ts_entrada > HORIZONTE_TIEMPO:
            precio_final = float(data.iloc[i - 1]["Close"])
            return "SIN_RESOLVER", ((precio_final - precio_entrada) / precio_entrada) * 100

        vela = data.iloc[i]
        toco_obj = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_obj and toco_stop:
            return "PERDIO", -stop_pct * 100
        if toco_obj:
            return "GANO", objetivo_pct * 100
        if toco_stop:
            return "PERDIO", -stop_pct * 100

    precio_final = float(data.iloc[fin - 1]["Close"])
    return "SIN_RESOLVER", ((precio_final - precio_entrada) / precio_entrada) * 100


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _generar_senales(data):
    """Recorre las velas una sola vez, evaluando las 13 señales de forma
    independiente (cada una con su propio enfriamiento)."""

    resultados = {nombre: [] for nombre in SENALES}
    en_posicion_hasta = {nombre: -1 for nombre in SENALES}

    for i in range(MIN_VELAS, len(data), PASO_VELAS):
        data_hasta_aqui = data.iloc[: i + 1]
        precio = float(data_hasta_aqui["Close"].iloc[-1])
        if precio != precio:
            continue

        try:
            data_ind = agregar_todos_los_indicadores(data_hasta_aqui)
            ultimo = data_ind.iloc[-1]
            score, _ = calcular_score(data_hasta_aqui)
        except Exception:
            continue

        condiciones = {"ScoreCombinado": score >= 80}
        try:
            condiciones.update(_evaluar_criterios_individuales(ultimo))
        except Exception:
            pass

        try:
            condiciones["TrendContinuation"] = _evaluar_trend_continuation(data_hasta_aqui)
            condiciones["LiquiditySweep"] = _evaluar_liquidity_sweep(data_hasta_aqui)
            condiciones["VolumeProfile"] = _evaluar_volume_profile(data_hasta_aqui)
            condiciones["MarketProfile"] = _evaluar_market_profile(data_hasta_aqui)
        except Exception:
            pass

        for nombre, cumple in condiciones.items():
            if not cumple or i <= en_posicion_hasta.get(nombre, -1):
                continue
            resultado, variacion = _simular_resultado(data, i, precio)
            resultados[nombre].append((i, data.index[i], precio, resultado, variacion))
            en_posicion_hasta[nombre] = i + MAX_VELAS_ABS

    return resultados


def _generar_aleatorias(data, cantidad, semilla):
    random.seed(semilla)
    indices = [i for i in range(MIN_VELAS, len(data) - 1) if data.iloc[i]["Close"] == data.iloc[i]["Close"]]
    if not indices or cantidad == 0:
        return []
    salidas = []
    for _ in range(cantidad):
        i = random.choice(indices)
        precio = float(data.iloc[i]["Close"])
        resultado, variacion = _simular_resultado(data, i, precio)
        salidas.append((i, data.index[i], precio, resultado, variacion))
    return salidas


def _stats_dinero(lista):
    if not lista:
        return None
    variaciones = [v for (_, _, _, _, v) in lista]
    netos = [_calcular_dinero(v) for v in variaciones]
    ganaron = sum(1 for (_, _, _, r, _) in lista if r == "GANO")
    perdieron = sum(1 for (_, _, _, r, _) in lista if r == "PERDIO")
    resueltas = ganaron + perdieron
    win_rate = (ganaron / resueltas * 100) if resueltas else 0.0
    return {
        "n": len(lista), "win_rate": win_rate,
        "neto_promedio": sum(netos) / len(netos), "neto_total": sum(netos),
        "ganaron": ganaron, "perdieron": perdieron,
    }


def fase1_comparar_senales(dias):
    data = _cargar_datos(dias)
    if data is None:
        print("No se pudo cargar ECOPETROL.CL")
        return None

    print(f"Datos: {data.index[0].strftime('%Y-%m-%d')} a {data.index[-1].strftime('%Y-%m-%d')} "
          f"({len(data)} velas)")
    print(f"Regla de salida para esta comparación: objetivo +{OBJETIVO_PCT*100:.0f}% / "
          f"stop -{STOP_PCT*100:.0f}% / horizonte {HORIZONTE_TIEMPO.days} días")
    print()

    resultados = _generar_senales(data)

    print("=" * 100)
    print("COMPARACIÓN DE LAS 13 SEÑALES SOBRE ECOPETROL.CL")
    print("=" * 100)
    print(f"{'SEÑAL':20} {'N':>5} {'WIN RATE':>10} {'NETO PROM.':>14} {'NETO TOTAL':>16} {'VS. ALEATORIO':>16}")
    print("-" * 100)

    filas = []
    for nombre in SENALES:
        stats = _stats_dinero(resultados[nombre])
        if stats is None:
            filas.append((nombre, None, None))
            continue

        aleatorias = _generar_aleatorias(data, stats["n"], hash(nombre) % 10000)
        stats_random = _stats_dinero(aleatorias)

        filas.append((nombre, stats, stats_random))

    filas_validas = [f for f in filas if f[1] is not None]
    filas_validas.sort(key=lambda f: f[1]["neto_promedio"], reverse=True)
    filas_sin_datos = [f for f in filas if f[1] is None]

    for nombre, stats, stats_random in filas_validas + filas_sin_datos:
        if stats is None:
            print(f"{nombre:20} sin señales")
            continue
        vs_random = f"{stats_random['win_rate']:.1f}% (n={stats_random['n']})" if stats_random else "N/A"
        print(f"{nombre:20} {stats['n']:>5} {stats['win_rate']:>9.1f}% "
              f"${stats['neto_promedio']:>+13,.0f} ${stats['neto_total']:>+15,.0f} {vs_random:>16}")

    print("-" * 100)

    if filas_validas:
        mejor_nombre = filas_validas[0][0]
        print(f"Señal con mejor neto promedio por operación: {mejor_nombre}")
    else:
        mejor_nombre = None
        print("Ninguna señal generó operaciones suficientes.")

    print("=" * 100)

    return data, resultados, mejor_nombre


def fase2_afinar_objetivo_stop(data, resultados, nombre_senal):
    print()
    print("=" * 100)
    print(f"FASE 2: BARRIDO DE OBJETIVO/STOP PARA LA SEÑAL GANADORA ({nombre_senal})")
    print("=" * 100)

    entradas = sorted(resultados[nombre_senal], key=lambda x: x[1])
    punto_medio = len(entradas) // 2
    calib, valid = entradas[:punto_medio], entradas[punto_medio:]

    print(f"Señales: calibración={len(calib)} | validación={len(valid)}")

    if len(calib) < MIN_SENALES_CALIBRACION or len(valid) == 0:
        print("No hay suficientes señales de esta estrategia para calibración/validación "
              "por separado (esperado con una sola acción - la muestra es chica).")
        return

    print()
    print(f"{'OBJETIVO':>10} {'STOP':>8} {'N':>6} {'NETO PROMEDIO':>16}")
    print("-" * 100)

    mejor_combo, mejor_neto = None, float("-inf")

    for obj in GRID_OBJETIVO:
        for stp in GRID_STOP:
            variaciones = []
            for (idx, _, precio, _, _) in calib:
                _, v = _simular_resultado(data, idx, precio, obj, stp)
                variaciones.append(v)
            if not variaciones:
                continue
            netos = [_calcular_dinero(v) for v in variaciones]
            neto_prom = sum(netos) / len(netos)
            print(f"{obj*100:>9.1f}% {stp*100:>7.1f}% {len(variaciones):>6} ${neto_prom:>+15,.0f}")
            if len(variaciones) >= MIN_SENALES_CALIBRACION and neto_prom > mejor_neto:
                mejor_neto = neto_prom
                mejor_combo = (obj, stp)

    print("-" * 100)

    if mejor_combo is None:
        print("Sin combinación con suficientes señales en calibración.")
        return

    print(f"Mejor combinación en calibración: {mejor_combo[0]*100:.1f}% / {mejor_combo[1]*100:.1f}% "
          f"(neto promedio ${mejor_neto:+,.0f})")
    print()
    print("--- Validación fuera de muestra ---")

    for nombre, (obj, stp) in [("ORIGINAL (+3%/-1%)", (0.03, 0.01)),
                                (f"MEJOR ({mejor_combo[0]*100:.1f}%/{mejor_combo[1]*100:.1f}%)", mejor_combo)]:
        variaciones = []
        for (idx, _, precio, _, _) in valid:
            _, v = _simular_resultado(data, idx, precio, obj, stp)
            variaciones.append(v)
        netos = [_calcular_dinero(v) for v in variaciones]
        neto_total = sum(netos)
        neto_prom = neto_total / len(netos) if netos else 0
        print(f"  {nombre}: n={len(variaciones)} | neto total ${neto_total:+,.0f} | "
              f"promedio ${neto_prom:+,.0f}/operación")

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    args = parser.parse_args()

    resultado = fase1_comparar_senales(args.dias)
    if resultado:
        data, resultados, mejor_nombre = resultado
        if mejor_nombre:
            fase2_afinar_objetivo_stop(data, resultados, mejor_nombre)