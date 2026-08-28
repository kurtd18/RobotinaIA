"""
Backtest final: barrido de combinaciones objetivo/stop con validación fuera
de muestra, más simulación de dinero real.

Fase 1 (calibración): usa la PRIMERA MITAD cronológica de las señales para
probar una cuadrícula de combinaciones objetivo/stop, y elige la de mejor
expectativa (con al menos 20 señales, para no elegir por casualidad).

Fase 2 (validación): aplica esa combinación ganadora sobre la SEGUNDA MITAD
de las señales - datos que el barrido de la Fase 1 nunca vio - para
confirmar si de verdad funciona o si fue una casualidad del período de
calibración (esto es lo que evita el "curve fitting").

Simulación de dinero: sobre los resultados de validación, simula invertir
$5,000,000 COP por operación, con comisión de $7,000 COP de entrada y
$7,000 COP de salida, y muestra el resultado neto final.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_final_validacion.py
    python scripts/backtest_final_validacion.py --dias 60
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings
from scoring import calcular_score

TZ_BOGOTA = ZoneInfo("America/Bogota")

MIN_VELAS_PARA_SCORE = 40
HORIZONTE_TIEMPO = timedelta(days=3)  # antes: 200 velas (~16h). Ahora: 3 días reales.
MAX_VELAS_SIMULACION_ABS = 900  # límite de seguridad (cripto 24/7 en 3 días ~ 864 velas de 5min)
PASO_VELAS = 3

MONTO_POR_OPERACION = 5_000_000
COMISION_POR_LADO = 7_000

GRID_OBJETIVO = [0.015, 0.02, 0.025, 0.03, 0.04]
GRID_STOP = [0.01, 0.015, 0.02, 0.025, 0.03]

MIN_SENALES_CALIBRACION = 20


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
            en_posicion_hasta = i + MAX_VELAS_SIMULACION_ABS

    return entradas


def _simular_resultado(data, idx_entrada, precio_entrada, objetivo_pct, stop_pct):
    """Simula el resultado dando hasta HORIZONTE_TIEMPO (3 días reales) para
    que la señal llegue al objetivo o al stop, en vez de un número fijo de
    velas - así el horizonte es el mismo en tiempo real sin importar el
    horario de mercado de cada activo (BVC, EE.UU., cripto 24/7...)."""

    objetivo = precio_entrada * (1 + objetivo_pct)
    stop = precio_entrada * (1 - stop_pct)

    ts_entrada = data.index[idx_entrada]
    fin_absoluto = min(idx_entrada + MAX_VELAS_SIMULACION_ABS, len(data))

    for i in range(idx_entrada + 1, fin_absoluto):
        if data.index[i] - ts_entrada > HORIZONTE_TIEMPO:
            precio_final = float(data.iloc[i - 1]["Close"])
            variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
            return "SIN_RESOLVER", variacion

        vela = data.iloc[i]
        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_objetivo and toco_stop:
            return "PERDIO", -stop_pct * 100
        if toco_objetivo:
            return "GANO", objetivo_pct * 100
        if toco_stop:
            return "PERDIO", -stop_pct * 100

    precio_final = float(data.iloc[fin_absoluto - 1]["Close"])
    variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
    return "SIN_RESOLVER", variacion


def _stats(resultados):
    n = len(resultados)
    if n == 0:
        return None

    ganaron = sum(1 for r, _ in resultados if r == "GANO")
    perdieron = sum(1 for r, _ in resultados if r == "PERDIO")
    resueltas = ganaron + perdieron
    win_rate = (ganaron / resueltas * 100) if resueltas else 0.0

    return {"n": n, "win_rate": win_rate, "ganaron": ganaron, "perdieron": perdieron, "resueltas": resueltas}


def _simular_dinero(resultados, monto=MONTO_POR_OPERACION, comision=COMISION_POR_LADO):
    neto_total = 0.0
    ganadoras_dinero = 0
    perdedoras_dinero = 0

    for resultado, variacion_pct in resultados:
        ganancia_bruta = monto * (variacion_pct / 100)
        neto = ganancia_bruta - (comision * 2)
        neto_total += neto

        if neto > 0:
            ganadoras_dinero += 1
        else:
            perdedoras_dinero += 1

    total_operaciones = len(resultados)
    capital_desplegado = total_operaciones * monto
    rentabilidad_pct = (neto_total / capital_desplegado * 100) if capital_desplegado else 0

    return {
        "total_operaciones": total_operaciones,
        "neto_total": neto_total,
        "capital_desplegado": capital_desplegado,
        "rentabilidad_pct": rentabilidad_pct,
        "ganadoras_dinero": ganadoras_dinero,
        "perdedoras_dinero": perdedoras_dinero,
    }


def _dividir_calibracion_validacion(entradas):
    """Divide las entradas por tiempo: la primera mitad cronológica es
    calibración, la segunda mitad (que el barrido nunca ve) es validación."""

    if not entradas:
        return [], []

    entradas_ordenadas = sorted(entradas, key=lambda e: e.entrada_ts)
    punto_medio = len(entradas_ordenadas) // 2

    return entradas_ordenadas[:punto_medio], entradas_ordenadas[punto_medio:]


COMISION_PCT_ROUND_TRIP = (COMISION_POR_LADO * 2 / MONTO_POR_OPERACION) * 100  # ej. 0.28%


def _calcular_expectativa(stats, objetivo_pct, stop_pct):
    if stats["resueltas"] == 0:
        return float("-inf")
    return (
        (stats["ganaron"] / stats["resueltas"]) * (objetivo_pct * 100)
        - (stats["perdieron"] / stats["resueltas"]) * (stop_pct * 100)
    )


def _calcular_expectativa_neta(stats, objetivo_pct, stop_pct):
    """Igual que _calcular_expectativa, pero restando el costo real de
    comisión (entrada + salida) - este es el número que de verdad importa
    para decidir si una combinación es rentable o no."""

    bruta = _calcular_expectativa(stats, objetivo_pct, stop_pct)
    if bruta == float("-inf"):
        return bruta
    return bruta - COMISION_PCT_ROUND_TRIP


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

    calibracion_por_symbol = {}
    validacion_por_symbol = {}
    total_calibracion = 0
    total_validacion = 0

    for symbol, entradas in entradas_por_symbol.items():
        calib, valid = _dividir_calibracion_validacion(entradas)
        calibracion_por_symbol[symbol] = calib
        validacion_por_symbol[symbol] = valid
        total_calibracion += len(calib)
        total_validacion += len(valid)

    print()
    print(f"Señales totales: calibración={total_calibracion} | validación={total_validacion}")
    print()

    # --- Fase 1: barrido en calibración ---
    print("=" * 100)
    print("FASE 1: BARRIDO DE OBJETIVO/STOP EN CALIBRACIÓN (primera mitad cronológica)")
    print("=" * 100)
    print(f"{'OBJETIVO':>10} {'STOP':>8} {'N':>6} {'WIN RATE':>10} {'EXPECT. BRUTA':>14} {'EXPECT. NETA':>13}")
    print("-" * 100)

    mejor_combo = None
    mejor_expectativa_neta = float("-inf")

    for objetivo_pct in GRID_OBJETIVO:
        for stop_pct in GRID_STOP:
            resultados = []
            for symbol, calib in calibracion_por_symbol.items():
                data = datos_por_symbol[symbol]
                for entrada in calib:
                    r, v = _simular_resultado(data, entrada.idx, entrada.entrada_precio, objetivo_pct, stop_pct)
                    resultados.append((r, v))

            stats = _stats(resultados)
            if stats is None or stats["resueltas"] == 0:
                continue

            expectativa_bruta = _calcular_expectativa(stats, objetivo_pct, stop_pct)
            expectativa_neta = _calcular_expectativa_neta(stats, objetivo_pct, stop_pct)

            print(f"{objetivo_pct*100:>9.1f}% {stop_pct*100:>7.1f}% {stats['n']:>6} "
                  f"{stats['win_rate']:>9.1f}% {expectativa_bruta:>+13.3f}% {expectativa_neta:>+12.3f}%")

            if stats["n"] >= MIN_SENALES_CALIBRACION and expectativa_neta > mejor_expectativa_neta:
                mejor_expectativa_neta = expectativa_neta
                mejor_combo = (objetivo_pct, stop_pct)

    print("-" * 100)
    print(f"(Comisión de ida y vuelta: {COMISION_PCT_ROUND_TRIP:.3f}% del monto invertido - "
          f"ya restada en la columna 'EXPECT. NETA')")
    print()

    if mejor_combo is None:
        print("No se encontró ninguna combinación con expectativa neta positiva y suficientes señales.")
        return

    print(f"Mejor combinación en calibración (por expectativa NETA de comisión): "
          f"objetivo={mejor_combo[0]*100:.1f}% / stop={mejor_combo[1]*100:.1f}% "
          f"(expectativa neta {mejor_expectativa_neta:+.3f}%)")
    print("=" * 100)

    # --- Fase 2: validar en la segunda mitad (fuera de muestra) ---
    print()
    print("=" * 100)
    print("FASE 2: VALIDACIÓN FUERA DE MUESTRA (segunda mitad, nunca vista en la Fase 1)")
    print("=" * 100)

    combos_a_validar = [
        ("ORIGINAL (+3%/-1%)", (0.03, 0.01)),
        ("C (+3%/-2%)", (0.03, 0.02)),
        (f"MEJOR DE CALIBRACIÓN ({mejor_combo[0]*100:.1f}%/{mejor_combo[1]*100:.1f}%)", mejor_combo),
    ]
    for nombre, (objetivo_pct, stop_pct) in combos_a_validar:
        resultados_validacion = []
        for symbol, valid in validacion_por_symbol.items():
            data = datos_por_symbol[symbol]
            for entrada in valid:
                r, v = _simular_resultado(data, entrada.idx, entrada.entrada_precio, objetivo_pct, stop_pct)
                resultados_validacion.append((r, v))

        stats = _stats(resultados_validacion)

        print(f"\n{nombre}")

        if stats is None or stats["resueltas"] == 0:
            print("  Sin datos suficientes en validación.")
            continue

        expectativa_bruta = _calcular_expectativa(stats, objetivo_pct, stop_pct)
        expectativa_neta = _calcular_expectativa_neta(stats, objetivo_pct, stop_pct)
        print(f"  N={stats['n']} | Win rate={stats['win_rate']:.1f}% | "
              f"Expectativa bruta={expectativa_bruta:+.3f}% | Expectativa neta={expectativa_neta:+.3f}%")

        dinero = _simular_dinero(resultados_validacion)
        print(f"  --- Simulación de dinero (${MONTO_POR_OPERACION:,.0f} COP/operación, "
              f"comisión ${COMISION_POR_LADO:,.0f} COP x lado) ---")
        print(f"  Operaciones: {dinero['total_operaciones']} | "
              f"Capital desplegado total: ${dinero['capital_desplegado']:,.0f} COP")
        print(f"  Resultado neto: ${dinero['neto_total']:,.0f} COP "
              f"({dinero['rentabilidad_pct']:+.2f}% sobre el capital desplegado)")
        print(f"  Operaciones netas positivas: {dinero['ganadoras_dinero']} | "
              f"netas negativas: {dinero['perdedoras_dinero']}")

    print()
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    parser.add_argument("--activos", type=str, default=None)
    args = parser.parse_args()

    activos = args.activos.split(",") if args.activos else Settings.todos_los_activos()

    correr(args.dias, activos)