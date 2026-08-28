"""
Backtest de 4 estrategias institucionales nuevas, cada una probada por
separado (no combinadas), usando el mismo motor de backtest ya validado
(mismo _simular_resultado, mismo grupo de control aleatorio) que los
scripts anteriores.

Estrategias incluidas:
  - Trend Continuation: EMA20 > EMA50, precio sobre VWAP, pullback a EMA20
    con rebote y volumen creciente.
  - Liquidity Sweep: el precio rompe un mínimo reciente (barrido de stops)
    y cierra de vuelta por encima de ese nivel en la misma vela.
  - Volume Profile (aproximado con velas de 5 min, no con datos tick):
    precio cerrando por encima del punto de control (POC) de volumen.
  - Market Profile (aproximado, basado en tiempo en vez de volumen):
    precio rompiendo por encima del Value Area High.

Order Flow y Opening Range Breakout NO están incluidos (ver docs/BACKLOG.md
Épica 17 para el porqué).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_estrategias_nuevas.py
    python scripts/backtest_estrategias_nuevas.py --dias 60
    python scripts/backtest_estrategias_nuevas.py --activos AAPL,MINEROS.CL
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas_ta as ta
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings
from scoring import STOP_INICIAL_PCT, OBJETIVO_INICIAL_PCT

TZ_BOGOTA = ZoneInfo("America/Bogota")

MIN_VELAS_PARA_SCORE = 110  # EMA50 + margen de pullback necesitan bastante historia
MAX_VELAS_SIMULACION = 200
PASO_VELAS = 3

VENTANA_PERFIL = 100  # velas hacia atrás para armar el perfil de volumen/mercado
N_BINS_PERFIL = 20    # niveles de precio en que se divide el perfil

ESTRATEGIAS = ["TrendContinuation", "LiquiditySweep", "VolumeProfile", "MarketProfile"]


@dataclass
class ResultadoSenal:
    symbol: str
    entrada_ts: object
    entrada_precio: float
    resultado: str
    variacion_pct: float
    velas_hasta_resolver: int


def _cargar_datos(symbol, dias):
    data = yf.Ticker(symbol).history(period=f"{dias}d", interval="5m")
    if data.empty:
        return None
    data.index = data.index.tz_convert(TZ_BOGOTA)
    return data


def _simular_resultado(data, idx_entrada, precio_entrada):
    objetivo = precio_entrada * (1 + OBJETIVO_INICIAL_PCT)
    stop = precio_entrada * (1 - STOP_INICIAL_PCT)
    fin = min(idx_entrada + MAX_VELAS_SIMULACION, len(data))

    for i in range(idx_entrada + 1, fin):
        vela = data.iloc[i]
        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop
        if toco_objetivo and toco_stop:
            return "PERDIO", -STOP_INICIAL_PCT * 100, i - idx_entrada
        if toco_objetivo:
            return "GANO", OBJETIVO_INICIAL_PCT * 100, i - idx_entrada
        if toco_stop:
            return "PERDIO", -STOP_INICIAL_PCT * 100, i - idx_entrada

    precio_final = float(data.iloc[fin - 1]["Close"])
    variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
    return "SIN_RESOLVER", variacion, fin - idx_entrada - 1


# --------------------------------------------------------------------------
# Estrategia 1: Trend Continuation
# --------------------------------------------------------------------------

def _evaluar_trend_continuation(data_hasta_aqui):
    if len(data_hasta_aqui) < 55:
        return False

    ema20 = ta.ema(data_hasta_aqui["Close"], length=20)
    ema50 = ta.ema(data_hasta_aqui["Close"], length=50)
    vwap = ta.vwap(
        data_hasta_aqui["High"], data_hasta_aqui["Low"],
        data_hasta_aqui["Close"], data_hasta_aqui["Volume"],
    )

    if ema20 is None or ema50 is None or vwap is None:
        return False

    ultimo_ema20, ultimo_ema50 = ema20.iloc[-1], ema50.iloc[-1]
    ultimo_close = data_hasta_aqui["Close"].iloc[-1]
    ultimo_vwap = vwap.iloc[-1]

    if any(pd_isna(v) for v in (ultimo_ema20, ultimo_ema50, ultimo_close, ultimo_vwap)):
        return False

    tendencia_alcista = ultimo_ema20 > ultimo_ema50
    sobre_vwap = ultimo_close > ultimo_vwap

    ultimas_5_low = data_hasta_aqui["Low"].iloc[-5:]
    ema20_ultimas5 = ema20.iloc[-5:]
    hubo_pullback = bool((ultimas_5_low.values <= ema20_ultimas5.values).any())
    rebote_actual = ultimo_close > ultimo_ema20

    volumen_creciente = (
        data_hasta_aqui["Volume"].iloc[-1] > data_hasta_aqui["Volume"].iloc[-2]
    )

    return bool(tendencia_alcista and sobre_vwap and hubo_pullback and rebote_actual and volumen_creciente)


# --------------------------------------------------------------------------
# Estrategia 2: Liquidity Sweep
# --------------------------------------------------------------------------

def _evaluar_liquidity_sweep(data_hasta_aqui, ventana=20):
    if len(data_hasta_aqui) < ventana + 2:
        return False

    anteriores = data_hasta_aqui.iloc[-(ventana + 1):-1]
    minimo_reciente = anteriores["Low"].min()

    ultima = data_hasta_aqui.iloc[-1]

    rompio_el_minimo = ultima["Low"] < minimo_reciente
    cerro_de_vuelta_arriba = ultima["Close"] > minimo_reciente

    return bool(rompio_el_minimo and cerro_de_vuelta_arriba)


# --------------------------------------------------------------------------
# Estrategia 3: Volume Profile (aproximado)
# --------------------------------------------------------------------------

def _evaluar_volume_profile(data_hasta_aqui, ventana=VENTANA_PERFIL, n_bins=N_BINS_PERFIL):
    if len(data_hasta_aqui) < ventana + 2:
        return False

    ventana_datos = data_hasta_aqui.iloc[-ventana:]

    precio_min = ventana_datos["Low"].min()
    precio_max = ventana_datos["High"].max()

    if precio_max <= precio_min:
        return False

    bins = np.linspace(precio_min, precio_max, n_bins + 1)
    indices_bin = np.digitize(ventana_datos["Close"], bins) - 1
    indices_bin = np.clip(indices_bin, 0, n_bins - 1)

    volumen_por_bin = np.zeros(n_bins)
    for idx_bin, volumen in zip(indices_bin, ventana_datos["Volume"]):
        volumen_por_bin[idx_bin] += volumen

    poc_bin = int(np.argmax(volumen_por_bin))
    poc_precio = (bins[poc_bin] + bins[poc_bin + 1]) / 2

    ultimo_close = data_hasta_aqui["Close"].iloc[-1]

    return bool(ultimo_close > poc_precio)


# --------------------------------------------------------------------------
# Estrategia 4: Market Profile (aproximado, basado en tiempo)
# --------------------------------------------------------------------------

def _evaluar_market_profile(data_hasta_aqui, ventana=VENTANA_PERFIL, n_bins=N_BINS_PERFIL):
    if len(data_hasta_aqui) < ventana + 2:
        return False

    ventana_datos = data_hasta_aqui.iloc[-ventana:]

    precio_min = ventana_datos["Low"].min()
    precio_max = ventana_datos["High"].max()

    if precio_max <= precio_min:
        return False

    bins = np.linspace(precio_min, precio_max, n_bins + 1)
    indices_bin = np.digitize(ventana_datos["Close"], bins) - 1
    indices_bin = np.clip(indices_bin, 0, n_bins - 1)

    tiempo_por_bin = np.zeros(n_bins)
    for idx_bin in indices_bin:
        tiempo_por_bin[idx_bin] += 1

    orden = np.argsort(tiempo_por_bin)[::-1]
    total = tiempo_por_bin.sum()
    acumulado = 0
    bins_value_area = []
    for idx_bin in orden:
        acumulado += tiempo_por_bin[idx_bin]
        bins_value_area.append(idx_bin)
        if acumulado >= total * 0.70:
            break

    value_area_high_bin = max(bins_value_area)
    value_area_high_precio = bins[value_area_high_bin + 1]

    ultimo_close = data_hasta_aqui["Close"].iloc[-1]

    return bool(ultimo_close > value_area_high_precio)


def pd_isna(valor):
    try:
        return valor != valor
    except Exception:
        return valor is None


def _evaluar_condiciones(data_hasta_aqui):
    return {
        "TrendContinuation": _evaluar_trend_continuation(data_hasta_aqui),
        "LiquiditySweep": _evaluar_liquidity_sweep(data_hasta_aqui),
        "VolumeProfile": _evaluar_volume_profile(data_hasta_aqui),
        "MarketProfile": _evaluar_market_profile(data_hasta_aqui),
    }


def _generar_senales_por_estrategia(symbol, data):
    resultados = {nombre: [] for nombre in ESTRATEGIAS}
    en_posicion_hasta = {nombre: -1 for nombre in ESTRATEGIAS}

    for i in range(MIN_VELAS_PARA_SCORE, len(data), PASO_VELAS):
        data_hasta_aqui = data.iloc[: i + 1]
        precio = float(data_hasta_aqui["Close"].iloc[-1])

        if precio != precio:
            continue

        try:
            condiciones = _evaluar_condiciones(data_hasta_aqui)
        except Exception:
            continue

        for nombre, cumple in condiciones.items():
            if not cumple or i <= en_posicion_hasta[nombre]:
                continue

            resultado, variacion, velas = _simular_resultado(data, i, precio)

            resultados[nombre].append(ResultadoSenal(
                symbol=symbol, entrada_ts=data.index[i], entrada_precio=precio,
                resultado=resultado, variacion_pct=variacion, velas_hasta_resolver=velas,
            ))
            en_posicion_hasta[nombre] = i + velas

    return resultados


def _generar_senales_aleatorias(data, cantidad, semilla):
    random.seed(semilla)
    senales = []

    indices_disponibles = [
        i for i in range(MIN_VELAS_PARA_SCORE, len(data) - 1)
        if data.iloc[i]["Close"] == data.iloc[i]["Close"]
    ]

    if not indices_disponibles or cantidad == 0:
        return senales

    for _ in range(cantidad):
        i = random.choice(indices_disponibles)
        precio = float(data.iloc[i]["Close"])
        resultado, variacion, velas = _simular_resultado(data, i, precio)
        senales.append(ResultadoSenal(
            symbol="RANDOM", entrada_ts=data.index[i], entrada_precio=precio,
            resultado=resultado, variacion_pct=variacion, velas_hasta_resolver=velas,
        ))

    return senales


def _calcular_stats(senales):
    n = len(senales)
    if n == 0:
        return None

    ganaron = [s for s in senales if s.resultado == "GANO"]
    perdieron = [s for s in senales if s.resultado == "PERDIO"]
    resueltas = len(ganaron) + len(perdieron)
    win_rate = (len(ganaron) / resueltas * 100) if resueltas else 0.0

    expectativa = (
        (len(ganaron) / resueltas) * (OBJETIVO_INICIAL_PCT * 100)
        + (len(perdieron) / resueltas) * (-STOP_INICIAL_PCT * 100)
    ) if resueltas else 0.0

    return {
        "n": n, "ganaron": len(ganaron), "perdieron": len(perdieron),
        "sin_resolver": n - resueltas, "win_rate": win_rate, "expectativa": expectativa,
    }


def correr_backtest(dias, activos):
    datos_por_symbol = {}

    for symbol in activos:
        print(f"Cargando {symbol}...")
        data = _cargar_datos(symbol, dias)
        if data is not None and len(data) >= MIN_VELAS_PARA_SCORE + 10:
            datos_por_symbol[symbol] = data

    print()
    print(f"{len(datos_por_symbol)} de {len(activos)} activos con datos suficientes.")
    print()

    senales_por_estrategia = {nombre: [] for nombre in ESTRATEGIAS}

    for symbol, data in datos_por_symbol.items():
        print(f"Procesando estrategias de {symbol}...")
        resultados = _generar_senales_por_estrategia(symbol, data)
        for nombre in ESTRATEGIAS:
            senales_por_estrategia[nombre].extend(resultados[nombre])

    print()
    print("=" * 100)
    print(f"{'ESTRATEGIA':18} {'N':>6} {'WIN RATE':>10} {'EXPECTATIVA':>13} {'VS. ALEATORIO (mismo N)':>26}")
    print("=" * 100)

    for nombre in ESTRATEGIAS:
        stats = _calcular_stats(senales_por_estrategia[nombre])

        if stats is None:
            print(f"{nombre:18} sin señales")
            continue

        random_agregado = []
        n_por_symbol = max(1, stats["n"] // max(1, len(datos_por_symbol)))
        for symbol, data in datos_por_symbol.items():
            random_agregado.extend(
                _generar_senales_aleatorias(data, n_por_symbol, hash((nombre, symbol)) % 10000)
            )

        stats_random = _calcular_stats(random_agregado)
        vs_random = f"{stats_random['win_rate']:.1f}% (n={stats_random['n']})" if stats_random else "N/A"

        alerta = "  ⚠️  <30" if stats["n"] < 30 else ""

        print(
            f"{nombre:18} {stats['n']:>6} {stats['win_rate']:>9.1f}% "
            f"{stats['expectativa']:>+12.2f}% {vs_random:>26}{alerta}"
        )

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    parser.add_argument("--activos", type=str, default=None)
    args = parser.parse_args()

    activos = args.activos.split(",") if args.activos else Settings.todos_los_activos()

    correr_backtest(args.dias, activos)