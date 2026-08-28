"""
Backtest completo (barrido + validación fuera de muestra + dinero real)
limitado a 10 acciones específicas de la BVC.

Fase 1 (calibración): usa la PRIMERA MITAD cronológica de las señales de
cada acción para probar una cuadrícula de combinaciones objetivo/stop, y
elige la de mejor resultado NETO promedio por operación (ya con el método
exacto de comisión, no una aproximación).

Fase 2 (validación): aplica la combinación ganadora sobre la SEGUNDA
MITAD - datos que el barrido nunca vio - y muestra el resultado en dinero
real por cada una de las 10 acciones, más el total combinado.

Horizonte de resolución: 3 días de tiempo real (no cuenta velas, cuenta
tiempo transcurrido - importante porque cada acción opera en un horario
de mercado distinto).

Dinero: desembolso de $5,000,000 COP por operación, con la comisión de
entrada ($7,000) saliendo de ese monto, y la comisión de salida ($7,000)
descontada de lo recibido al vender.

Yahoo Finance no entrega velas de 5 minutos desde enero - su límite real
son unos 60-90 días hacia atrás sin importar cuánto se pida. El script
pide el máximo razonable y muestra el rango real que devolvió cada acción.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_10_acciones.py
    python scripts/backtest_10_acciones.py --dias 250
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
HORIZONTE_TIEMPO = timedelta(days=3)
MAX_VELAS_SIMULACION_ABS = 900
PASO_VELAS = 3

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

GRID_OBJETIVO = [0.015, 0.02, 0.025, 0.03, 0.04]
GRID_STOP = [0.01, 0.015, 0.02, 0.025, 0.03]

MIN_SENALES_CALIBRACION = 15  # más bajo que antes: son solo 10 acciones, menos señales totales

ACTIVOS = [
    "PFCIBEST.CL",   # Bancolombia Preferencial (renombrada a Grupo Cibest)
    "ECOPETROL.CL",  # Ecopetrol
    "GEB.CL",        # Grupo Energía Bogotá
    "GRUPOARGOS.CL", # Grupo Argos
    "CEMARGOS.CL",   # Cementos Argos
    "CELSIA.CL",     # Celsia
    "GRUPOSURA.CL",  # Grupo Sura
    "PFDAVVNDA.CL",  # Davivienda Preferencial
    "TERPEL.CL",     # Organización Terpel
    "NUTRESA.CL",    # Grupo Nutresa
]


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
    objetivo = precio_entrada * (1 + objetivo_pct)
    stop = precio_entrada * (1 - stop_pct)

    ts_entrada = data.index[idx_entrada]
    fin_absoluto = min(idx_entrada + MAX_VELAS_SIMULACION_ABS, len(data))

    for i in range(idx_entrada + 1, fin_absoluto):
        if data.index[i] - ts_entrada > HORIZONTE_TIEMPO:
            precio_final = float(data.iloc[i - 1]["Close"])
            variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
            return "SIN_RESOLVER", variacion, data.index[i - 1]

        vela = data.iloc[i]
        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_objetivo and toco_stop:
            return "PERDIO", -stop_pct * 100, data.index[i]
        if toco_objetivo:
            return "GANO", objetivo_pct * 100, data.index[i]
        if toco_stop:
            return "PERDIO", -stop_pct * 100, data.index[i]

    precio_final = float(data.iloc[fin_absoluto - 1]["Close"])
    variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
    return "SIN_RESOLVER", variacion, data.index[fin_absoluto - 1]


def _calcular_dinero_operacion(variacion_pct):
    """Comisión de entrada sale del desembolso; comisión de salida se
    descuenta de lo recibido al vender."""

    monto_invertido_real = DESEMBOLSO_TOTAL - COMISION
    valor_bruto_al_salir = monto_invertido_real * (1 + variacion_pct / 100)
    valor_neto_recibido = valor_bruto_al_salir - COMISION
    resultado_neto = valor_neto_recibido - DESEMBOLSO_TOTAL

    return resultado_neto, valor_neto_recibido


def _dividir_calibracion_validacion(entradas):
    if not entradas:
        return [], []
    entradas_ordenadas = sorted(entradas, key=lambda e: e.entrada_ts)
    punto_medio = len(entradas_ordenadas) // 2
    return entradas_ordenadas[:punto_medio], entradas_ordenadas[punto_medio:]


def correr(dias):
    datos_por_symbol = {}
    entradas_por_symbol = {}

    print("Cargando datos de las 10 acciones...")
    print()

    for symbol in ACTIVOS:
        data = _cargar_datos(symbol, dias)
        if data is None or len(data) < MIN_VELAS_PARA_SCORE + 10:
            print(f"  {symbol}: sin datos suficientes, se omite")
            continue

        datos_por_symbol[symbol] = data
        entradas_por_symbol[symbol] = _detectar_entradas(symbol, data)

        print(f"  {symbol:14} datos {data.index[0].strftime('%Y-%m-%d')} a "
              f"{data.index[-1].strftime('%Y-%m-%d')} "
              f"({(data.index[-1]-data.index[0]).days} días) | "
              f"{len(entradas_por_symbol[symbol])} señal(es) detectada(s)")

    print()

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

    print(f"Señales totales: calibración={total_calibracion} | validación={total_validacion}")
    print()

    # --- Fase 1: barrido en calibración, usando el NETO real promedio ---
    print("=" * 100)
    print("FASE 1: BARRIDO DE OBJETIVO/STOP EN CALIBRACIÓN (primera mitad cronológica)")
    print("=" * 100)
    print(f"{'OBJETIVO':>10} {'STOP':>8} {'N':>6} {'NETO PROMEDIO/OPERACIÓN':>26}")
    print("-" * 100)

    mejor_combo = None
    mejor_neto_promedio = float("-inf")

    for objetivo_pct in GRID_OBJETIVO:
        for stop_pct in GRID_STOP:
            variaciones = []
            for symbol, calib in calibracion_por_symbol.items():
                data = datos_por_symbol[symbol]
                for entrada in calib:
                    _, v, _ = _simular_resultado(data, entrada.idx, entrada.entrada_precio, objetivo_pct, stop_pct)
                    variaciones.append(v)

            if not variaciones:
                continue

            netos = [_calcular_dinero_operacion(v)[0] for v in variaciones]
            neto_promedio = sum(netos) / len(netos)

            print(f"{objetivo_pct*100:>9.1f}% {stop_pct*100:>7.1f}% {len(variaciones):>6} "
                  f"${neto_promedio:>+24,.0f}")

            if len(variaciones) >= MIN_SENALES_CALIBRACION and neto_promedio > mejor_neto_promedio:
                mejor_neto_promedio = neto_promedio
                mejor_combo = (objetivo_pct, stop_pct)

    print("-" * 100)

    if mejor_combo is None:
        print("No se encontró ninguna combinación con suficientes señales en calibración.")
        return

    print(f"Mejor combinación en calibración: objetivo={mejor_combo[0]*100:.1f}% / "
          f"stop={mejor_combo[1]*100:.1f}% (neto promedio ${mejor_neto_promedio:+,.0f} COP/operación)")
    print("=" * 100)

    # --- Fase 2: validación fuera de muestra, con desglose por acción ---
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
        print()
        print(f"--- {nombre} ---")

        neto_total = 0.0
        operaciones_total = 0
        ganaron_total = 0
        perdieron_total = 0

        for symbol, valid in validacion_por_symbol.items():
            if not valid:
                continue

            data = datos_por_symbol[symbol]
            neto_symbol = 0.0
            ganaron = 0
            perdieron = 0

            for entrada in valid:
                resultado, v, _ = _simular_resultado(data, entrada.idx, entrada.entrada_precio, objetivo_pct, stop_pct)
                neto, _ = _calcular_dinero_operacion(v)
                neto_symbol += neto

                if resultado == "GANO":
                    ganaron += 1
                elif resultado == "PERDIO":
                    perdieron += 1

            print(f"  {symbol:14} {len(valid):2} operación(es) | neto ${neto_symbol:+,.0f} COP "
                  f"(G={ganaron} P={perdieron} SR={len(valid)-ganaron-perdieron})")

            neto_total += neto_symbol
            operaciones_total += len(valid)
            ganaron_total += ganaron
            perdieron_total += perdieron

        print(f"  {'TOTAL':14} {operaciones_total:2} operación(es) | neto ${neto_total:+,.0f} COP "
              f"(G={ganaron_total} P={perdieron_total})")

    print()
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    args = parser.parse_args()

    correr(args.dias)