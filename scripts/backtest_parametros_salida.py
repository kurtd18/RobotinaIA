"""
Backtest de sensibilidad a la regla de salida (objetivo/stop).

Usa exactamente las mismas señales que detecta el sistema real hoy
(scoring.calcular_score >= UMBRAL_SENAL), pero simula el resultado con
distintas combinaciones de objetivo/stop sobre los MISMOS puntos de
entrada - así la comparación es limpia: si el problema estuviera en la
señal de entrada, cambiar la regla de salida no debería mejorar nada; si
el problema está en la regla de salida, aquí debería notarse.

Reglas probadas:
  - ORIGINAL (+3% / -1%): la que usa el sistema en producción hoy.
  - C (+3% / -2%): mismo objetivo, stop más amplio (¿el stop actual corta
    la posición antes de tiempo?).
  - D (+1.5% / -1.5%): simétrico 1:1, mide acierto direccional puro sin
    la asimetría premio/riesgo de por medio.

Nota: los puntos de entrada se detectan UNA sola vez con un enfriamiento
fijo (no depende de cuál regla de salida se esté probando), para que las
3 reglas se evalúen sobre exactamente el mismo conjunto de señales.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_parametros_salida.py
    python scripts/backtest_parametros_salida.py --dias 60
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings
from scoring import calcular_score

TZ_BOGOTA = ZoneInfo("America/Bogota")

MIN_VELAS_PARA_SCORE = 40
MAX_VELAS_SIMULACION = 200
PASO_VELAS = 3

REGLAS_SALIDA = {
    "ORIGINAL (+3%/-1%)": (0.03, 0.01),
    "C (+3%/-2%)": (0.03, 0.02),
    "D (+1.5%/-1.5%)": (0.015, 0.015),
}


@dataclass
class Entrada:
    symbol: str
    idx: int
    entrada_ts: object
    entrada_precio: float


def _cargar_datos(symbol, dias):
    data = yf.Ticker(symbol).history(period=f"{dias}d", interval="5m")
    if data.empty:
        return None
    data.index = data.index.tz_convert(TZ_BOGOTA)
    return data


def _detectar_entradas(symbol, data):
    entradas = []
    en_posicion_hasta = -1

    for i in range(MIN_VELAS_PARA_SCORE, len(data), PASO_VELAS):
        if i <= en_posicion_hasta:
            continue

        data_hasta_aqui = data.iloc[: i + 1]

        try:
            score, precio = calcular_score(data_hasta_aqui)
        except Exception:
            continue

        if score >= Settings.UMBRAL_SENAL:
            entradas.append(Entrada(symbol=symbol, idx=i, entrada_ts=data.index[i], entrada_precio=precio))
            en_posicion_hasta = i + MAX_VELAS_SIMULACION

    return entradas


def _simular_resultado(data, idx_entrada, precio_entrada, objetivo_pct, stop_pct):
    objetivo = precio_entrada * (1 + objetivo_pct)
    stop = precio_entrada * (1 - stop_pct)
    fin = min(idx_entrada + MAX_VELAS_SIMULACION, len(data))

    for i in range(idx_entrada + 1, fin):
        vela = data.iloc[i]
        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_objetivo and toco_stop:
            return "PERDIO", -stop_pct * 100
        if toco_objetivo:
            return "GANO", objetivo_pct * 100
        if toco_stop:
            return "PERDIO", -stop_pct * 100

    precio_final = float(data.iloc[fin - 1]["Close"])
    variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
    return "SIN_RESOLVER", variacion


def _generar_indices_aleatorios(data, cantidad, semilla):
    random.seed(semilla)
    indices_disponibles = [
        i for i in range(MIN_VELAS_PARA_SCORE, len(data) - 1)
        if data.iloc[i]["Close"] == data.iloc[i]["Close"]
    ]
    if not indices_disponibles or cantidad == 0:
        return []
    return [random.choice(indices_disponibles) for _ in range(cantidad)]


def _stats(resultados):
    n = len(resultados)
    if n == 0:
        return None

    ganaron = sum(1 for r, _ in resultados if r == "GANO")
    perdieron = sum(1 for r, _ in resultados if r == "PERDIO")
    resueltas = ganaron + perdieron
    win_rate = (ganaron / resueltas * 100) if resueltas else 0.0

    return {"n": n, "win_rate": win_rate, "ganaron": ganaron, "perdieron": perdieron, "resueltas": resueltas}


def correr(dias, activos):
    entradas_por_symbol = {}
    datos_por_symbol = {}

    for symbol in activos:
        print(f"Cargando y detectando señales en {symbol}...")
        data = _cargar_datos(symbol, dias)
        if data is None or len(data) < MIN_VELAS_PARA_SCORE + 10:
            continue
        datos_por_symbol[symbol] = data
        entradas_por_symbol[symbol] = _detectar_entradas(symbol, data)

    total_entradas = sum(len(v) for v in entradas_por_symbol.values())
    print()
    print(f"Total de señales detectadas (score >= {Settings.UMBRAL_SENAL}): {total_entradas}")
    print()

    print("=" * 100)
    print(f"{'REGLA DE SALIDA':20} {'N':>6} {'WIN RATE':>10} {'EXPECTATIVA':>13} {'VS. ALEATORIO':>20}")
    print("=" * 100)

    for nombre_regla, (objetivo_pct, stop_pct) in REGLAS_SALIDA.items():
        resultados_reales = []
        resultados_random = []

        for symbol, entradas in entradas_por_symbol.items():
            data = datos_por_symbol[symbol]

            for entrada in entradas:
                r, v = _simular_resultado(data, entrada.idx, entrada.entrada_precio, objetivo_pct, stop_pct)
                resultados_reales.append((r, v))

            indices_random = _generar_indices_aleatorios(
                data, len(entradas), hash((nombre_regla, symbol)) % 10000
            )
            for idx in indices_random:
                precio = float(data.iloc[idx]["Close"])
                r, v = _simular_resultado(data, idx, precio, objetivo_pct, stop_pct)
                resultados_random.append((r, v))

        stats_reales = _stats(resultados_reales)
        stats_random = _stats(resultados_random)

        if stats_reales is None or stats_reales["resueltas"] == 0:
            print(f"{nombre_regla:20} sin datos suficientes")
            continue

        expectativa = (
            (stats_reales["ganaron"] / stats_reales["resueltas"]) * (objetivo_pct * 100)
            - (stats_reales["perdieron"] / stats_reales["resueltas"]) * (stop_pct * 100)
        )

        vs_random = f"{stats_random['win_rate']:.1f}% (n={stats_random['n']})" if stats_random else "N/A"

        print(
            f"{nombre_regla:20} {stats_reales['n']:>6} {stats_reales['win_rate']:>9.1f}% "
            f"{expectativa:>+12.2f}% {vs_random:>20}"
        )

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    parser.add_argument("--activos", type=str, default=None)
    args = parser.parse_args()

    activos = args.activos.split(",") if args.activos else Settings.todos_los_activos()

    correr(args.dias, activos)