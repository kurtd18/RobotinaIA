"""
Backtest de estrategia SHORT (apostar a la baja) para ADAUSDT, velas de
4 horas, 2026 - motivado por el hallazgo de que las subidas fuertes a
esta escala tienden a revertir (percentil 8 en el control de Monte
Carlo, horizonte de 96h).

Señal de entrada: el momento en que el "run-up" (subida desde el mínimo
de las últimas 20 velas) cruza el percentil 75 de sus propias subidas
históricas - se entra en SHORT ahí, apostando a que revierta.

Salida: trailing stop INVERTIDO (para short):
  - Stop inicial por ENCIMA de la entrada (pierdes si el precio sube)
  - Objetivo inicial por DEBAJO de la entrada (ganas si el precio baja)
  - Cuando se toca el objetivo vigente, ESE NIVEL se convierte en el
    nuevo stop, y el siguiente objetivo baja más - el stop va bajando
    detrás del precio mientras siga cayendo a favor.

Dinero: en un short, ganas cuando el precio BAJA (al revés que en largo).
Mismo desembolso $5,000,000 COP, comisión $7,000 COP por lado.

Calibración/validación fuera de muestra, y grupo de control aleatorio.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_short_ada_4h.py
"""

import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

SYMBOL = "ADAUSDT"
FECHA_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)
VENTANA_MINIMO = 20  # velas de 4h

STOP_INICIAL_PCT = 0.05     # el precio sube 5% -> pierdes
OBJETIVO_INICIAL_PCT = 0.08  # el precio baja 8% -> primer nivel, se vuelve el nuevo stop
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    return data[data["Volume"] > 0]


def _calcular_dinero_short(variacion_pct):
    """En short, variacion_pct positivo significa que el precio BAJÓ
    (ganancia) - se invierte el signo respecto al cálculo normal de
    largo, pero la mecánica de comisión es la misma."""

    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_runup(data, ventana_minimo, umbral_runup):
    minimo_reciente = data["Close"].rolling(ventana_minimo).min().shift(1)
    runup_pct = (data["Close"] - minimo_reciente) / minimo_reciente * 100

    cruces = []
    for i in range(ventana_minimo + 1, len(data)):
        ru_hoy = runup_pct.iloc[i]
        ru_ayer = runup_pct.iloc[i - 1]

        if ru_hoy != ru_hoy or ru_ayer != ru_ayer:
            continue

        if ru_ayer < umbral_runup and ru_hoy >= umbral_runup:
            cruces.append(i)

    return cruces


def _simular_trailing_stop_short(data, idx_entrada, entrada_precio):
    """Trailing stop invertido: stop arriba (pérdida si sube), objetivo
    abajo (ganancia si baja), el stop baja detrás del precio."""

    stop = entrada_precio * (1 + STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 - OBJETIVO_INICIAL_PCT)

    n = len(data)

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]

        # Si el precio sube y toca el stop (por encima) -> se vende con pérdida
        if high >= stop:
            variacion_pct = ((entrada_precio - stop) / entrada_precio) * 100
            return variacion_pct, data.index[i]

        # Si el precio baja y toca el objetivo vigente, ese nivel se
        # vuelve el nuevo stop, y el siguiente objetivo baja más
        while low <= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 - INCREMENTO_PCT)

    precio_final = float(data["Close"].iloc[-1])
    variacion_pct = ((entrada_precio - precio_final) / entrada_precio) * 100
    return variacion_pct, data.index[-1]


@dataclass
class Operacion:
    entrada_fecha: object
    entrada_precio: float
    variacion_pct: float
    neto: float


def _simular_operaciones(data, indices_entrada):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        variacion_pct, salida_fecha = _simular_trailing_stop_short(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        neto = _calcular_dinero_short(variacion_pct)

        operaciones.append(Operacion(entrada_fecha, entrada_precio, variacion_pct, neto))
        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(data, cantidad, semilla, minimo_idx):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(data, sorted(set(indices_random)))


def correr():
    print(f"Estrategia SHORT: {SYMBOL}, velas de 4h, desde {FECHA_INICIO.strftime('%Y-%m-%d')}")
    print(f"Salida: trailing stop invertido (+{STOP_INICIAL_PCT*100:.1f}% stop / "
          f"-{OBJETIVO_INICIAL_PCT*100:.1f}% objetivo / -{INCREMENTO_PCT*100:.0f}% incremento)")
    print()

    data = obtener_klines(SYMBOL, "4h", FECHA_INICIO)
    if data is None or len(data) < VENTANA_MINIMO + 30:
        print("Sin datos suficientes.")
        return

    data = _limpiar_datos(data)
    print(f"Datos: {data.index[0].strftime('%Y-%m-%d %H:%M')} a {data.index[-1].strftime('%Y-%m-%d %H:%M')} "
          f"({len(data)} velas)")

    # Umbral de entrada: percentil 75 de las subidas reales de ADA a 4h
    minimo_reciente = data["Close"].rolling(VENTANA_MINIMO).min().shift(1)
    runup_pct = (data["Close"] - minimo_reciente) / minimo_reciente * 100
    runups_validos = runup_pct.dropna()
    runups_positivos = runups_validos[runups_validos > 0]
    umbral_runup = float(runups_positivos.quantile(0.75))

    print(f"Umbral de entrada (percentil 75 de subidas reales): {umbral_runup:.2f}%")
    print()

    cruces = _detectar_cruces_runup(data, VENTANA_MINIMO, umbral_runup)
    operaciones = _simular_operaciones(data, cruces)

    print(f"Operaciones totales: {len(operaciones)}")
    print()

    if not operaciones:
        print("No se generaron operaciones.")
        return

    for op in operaciones:
        print(f"  {op.entrada_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.entrada_precio:,.4f} | "
              f"{op.variacion_pct:+.2f}% | neto {op.neto:+,.0f} COP")

    punto_medio = len(operaciones) // 2
    calib = operaciones[:punto_medio]
    valid = operaciones[punto_medio:]

    print()
    print("=" * 100)
    print(f"CALIBRACIÓN: {len(calib)} operaciones")
    print("=" * 100)
    if calib:
        neto_calib = sum(op.neto for op in calib)
        ganaron_calib = sum(1 for op in calib if op.neto > 0)
        print(f"Neto total: ${neto_calib:+,.0f} COP | Ganadoras: {ganaron_calib}/{len(calib)} "
              f"({ganaron_calib/len(calib)*100:.1f}%)")

    print()
    print("=" * 100)
    print(f"VALIDACIÓN FUERA DE MUESTRA: {len(valid)} operaciones")
    print("=" * 100)
    if valid:
        neto_valid = sum(op.neto for op in valid)
        ganaron_valid = sum(1 for op in valid if op.neto > 0)
        print(f"Neto total: ${neto_valid:+,.0f} COP | Ganadoras: {ganaron_valid}/{len(valid)} "
              f"({ganaron_valid/len(valid)*100:.1f}%)")

        aleatorias = _generar_aleatorias(data, len(valid), 777, VENTANA_MINIMO)
        neto_random = sum(op.neto for op in aleatorias)
        print(f"Grupo de control aleatorio (mismo tamaño): {len(aleatorias)} operaciones | "
              f"neto ${neto_random:+,.0f} COP")

        if len(valid) < 30:
            print("⚠️  Muestra menor a 30 - resultado indicativo, no concluyente todavía.")

    print("=" * 100)


if __name__ == "__main__":
    correr()