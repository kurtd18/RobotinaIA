"""
Backtest de "Market Profile" (aproximado, basado en tiempo en cada nivel
de precio - no en datos tick reales) como señal de entrada, en velas
DIARIAS (para tener muestra grande y periodo largo, a diferencia de la
prueba anterior con solo 4 operaciones en velas de 5 minutos), combinada
con el trailing stop real, sobre las 10 acciones BVC.

Señal de entrada: se arma un histograma de "tiempo pasado en cada nivel
de precio" usando los cierres de los últimos N días (por defecto 100).
Se calcula el Value Area (el rango de precio donde ocurrió ~70% del
tiempo) y su límite superior (Value Area High). Cuando el cierre de hoy
rompe por encima del Value Area High, se compra - interpretación: el
mercado estaba "balanceado" en un rango, y ahora se está volviendo
direccional hacia arriba.

Salida: mismo trailing stop real (stop inicial -1.5%, objetivo inicial
+3%, incrementos de +1%).

Dinero: mismo método validado (desembolso $5,000,000 COP, comisión
$7,000 COP por lado).

Se compara contra un grupo de control aleatorio del mismo tamaño.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_market_profile_bvc.py
    python scripts/backtest_market_profile_bvc.py --ventana 100
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

UMBRAL_ANOMALIA = 15.0
N_BINS = 20

STOP_INICIAL_PCT = 0.015
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


def _value_area_high(data, idx, ventana, n_bins):
    """Calcula el Value Area High (límite superior de la zona donde el
    precio pasó ~70% del tiempo) usando los `ventana` días anteriores al
    índice `idx` (sin incluir el día actual)."""

    if idx < ventana:
        return None

    v = data.iloc[idx - ventana: idx]

    pmin, pmax = float(v["Low"].min()), float(v["High"].max())
    if pmax <= pmin:
        return None

    bins = np.linspace(pmin, pmax, n_bins + 1)
    idx_bin = np.clip(np.digitize(v["Close"], bins) - 1, 0, n_bins - 1)

    tiempo_bin = np.zeros(n_bins)
    for i_bin in idx_bin:
        tiempo_bin[i_bin] += 1

    orden = np.argsort(tiempo_bin)[::-1]
    total = tiempo_bin.sum()
    acumulado, bins_va = 0, []
    for i_bin in orden:
        acumulado += tiempo_bin[i_bin]
        bins_va.append(i_bin)
        if acumulado >= total * 0.70:
            break

    vah_bin = max(bins_va)
    return bins[vah_bin + 1]


def _detectar_rupturas_value_area(data, ventana, n_bins):
    rupturas = []

    for i in range(ventana, len(data)):
        vah = _value_area_high(data, i, ventana, n_bins)
        if vah is None:
            continue

        if float(data["Close"].iloc[i]) > vah:
            rupturas.append(i)

    return rupturas


def _simular_trailing_stop(data, idx_entrada, entrada_precio, objetivo_inicial_pct):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + objetivo_inicial_pct)

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


def _simular_operaciones(data, indices_entrada, objetivo_inicial_pct):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(
            data, idx_entrada, entrada_precio, objetivo_inicial_pct
        )

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        operaciones.append(Operacion(entrada_fecha, entrada_precio, variacion_pct))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(data, cantidad, semilla, ventana, objetivo_inicial_pct):
    random.seed(semilla)
    indices = list(range(ventana, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(data, sorted(set(indices_random)), objetivo_inicial_pct)


def correr(fecha_inicio, ventana, objetivo_inicial_pct):
    print(f"Señal: ruptura del Value Area High (Market Profile, ventana de {ventana} días)")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}%/+{objetivo_inicial_pct*100:.1f}%/"
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
        rupturas = _detectar_rupturas_value_area(data, ventana, N_BINS)
        operaciones = _simular_operaciones(data, rupturas, objetivo_inicial_pct)

        neto_symbol = sum(_calcular_dinero(op.variacion_pct) for op in operaciones)

        aleatorias = _generar_aleatorias(data, len(operaciones), hash(symbol) % 10000, ventana, objetivo_inicial_pct)
        neto_random = sum(_calcular_dinero(op.variacion_pct) for op in aleatorias)

        print(f"{symbol:14} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP  |  "
              f"aleatorio: {len(aleatorias)} ops, ${neto_random:+,.0f} COP")

        neto_total += neto_symbol
        n_total += len(operaciones)
        neto_total_random += neto_random
        n_total_random += len(aleatorias)

    print()
    print("=" * 90)
    print(f"TOTAL MARKET PROFILE:  {n_total} operaciones | neto ${neto_total:+,.0f} COP")
    print(f"TOTAL ALEATORIO:       {n_total_random} operaciones | neto ${neto_total_random:+,.0f} COP")
    if n_total < 30:
        print("⚠️  Muestra menor a 30 - no es suficiente para conclusiones firmes.")
    print("=" * 90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--ventana", type=int, default=100)
    parser.add_argument("--objetivo", type=float, default=0.03)
    args = parser.parse_args()

    correr(args.inicio, args.ventana, args.objetivo)