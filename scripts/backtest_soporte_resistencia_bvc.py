"""
Backtest de "rompimiento de resistencia" (estructura de precio, nunca
antes probada en esta sesión) como señal de entrada, combinada con el
trailing stop real, sobre las 10 acciones BVC.

Señal de entrada: el cierre de hoy supera el máximo de los últimos N días
(por defecto 20) - un rompimiento limpio de la resistencia reciente. Se
compra al cierre de ese día.

Salida: mismo trailing stop real (stop inicial -1.5%, objetivo inicial
+3%, incrementos de +1%).

Dinero: mismo método validado (desembolso $5,000,000 COP, comisión
$7,000 COP por lado).

Se compara contra un grupo de control aleatorio del mismo tamaño.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_soporte_resistencia_bvc.py
    python scripts/backtest_soporte_resistencia_bvc.py --ventana 20
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

UMBRAL_ANOMALIA = 15.0

STOP_INICIAL_PCT = 0.015
OBJETIVO_INICIAL_PCT = 0.03
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _cargar_datos_diarios(symbol, fecha_inicio):
    data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_rompimientos(data, ventana):
    """Devuelve los índices donde el cierre de hoy supera el máximo (High)
    de los últimos `ventana` días ANTERIORES (sin incluir hoy)."""

    resistencia = data["High"].rolling(ventana).max().shift(1)

    rompimientos = []
    for i in range(ventana + 1, len(data)):
        res = resistencia.iloc[i]
        if res != res:  # NaN
            continue
        if data["Close"].iloc[i] > res:
            rompimientos.append(i)

    return rompimientos


def _simular_trailing_stop(data, idx_entrada, entrada_precio):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + OBJETIVO_INICIAL_PCT)

    n = len(data)

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]

        if low <= stop:
            return "VENDIO", float(stop), data.index[i]

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + INCREMENTO_PCT)

    precio_final = float(data["Close"].iloc[-1])
    return "SIN_RESOLVER", precio_final, data.index[-1]


@dataclass
class Operacion:
    entrada_fecha: object
    entrada_precio: float
    variacion_pct: float


def _simular_operaciones(data, indices_entrada):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        operaciones.append(Operacion(entrada_fecha, entrada_precio, variacion_pct))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(data, cantidad, semilla, ventana):
    random.seed(semilla)
    indices = list(range(ventana + 1, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(data, sorted(set(indices_random)))


def correr(fecha_inicio, ventana):
    print(f"Señal: rompimiento de resistencia (cierre supera el máximo de los últimos {ventana} días)")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}%/+{OBJETIVO_INICIAL_PCT*100:.0f}%/"
          f"+{INCREMENTO_PCT*100:.0f}%)")
    print()

    neto_total = 0.0
    n_total = 0
    neto_total_random = 0.0
    n_total_random = 0

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < ventana + 20:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _filtrar_anomalias(data)
        rompimientos = _detectar_rompimientos(data, ventana)
        operaciones = _simular_operaciones(data, rompimientos)

        neto_symbol = sum(_calcular_dinero(op.variacion_pct) for op in operaciones)

        aleatorias = _generar_aleatorias(data, len(operaciones), hash(symbol) % 10000, ventana)
        neto_random = sum(_calcular_dinero(op.variacion_pct) for op in aleatorias)

        print(f"{symbol:14} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP  |  "
              f"aleatorio: {len(aleatorias)} ops, ${neto_random:+,.0f} COP")

        neto_total += neto_symbol
        n_total += len(operaciones)
        neto_total_random += neto_random
        n_total_random += len(aleatorias)

    print()
    print("=" * 90)
    print(f"TOTAL SEÑAL ROMPIMIENTO:  {n_total} operaciones | neto ${neto_total:+,.0f} COP")
    print(f"TOTAL ALEATORIO:          {n_total_random} operaciones | neto ${neto_total_random:+,.0f} COP")
    if n_total < 30:
        print("⚠️  Muestra menor a 30 - no es suficiente para conclusiones firmes.")
    print("=" * 90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--ventana", type=int, default=20)
    args = parser.parse_args()

    correr(args.inicio, args.ventana)