"""
Prueba la señal de "drawdown -10% desde el máximo de 20 días + trailing
stop amplio" (encontrada y validada en las 10 acciones BVC) sobre el
universo COMPLETO de 63 activos que usamos al inicio de la sesión (BVC +
acciones internacionales + ETF + cripto, todo vía Yahoo Finance), con
datos diarios desde 2018 - la muestra más grande y diversa que podemos
armar sin salir de Yahoo Finance.

Señal de entrada: el momento exacto en que el drawdown desde el máximo de
20 días cruza a -10% o más.

Salida: trailing stop real (stop inicial -5%, objetivo inicial +8%,
incrementos de +1% - los mismos parámetros que dieron el mejor resultado
en BVC).

Dinero: desembolso $5,000,000 COP por operación, comisión $7,000 COP por
lado.

Calibración/validación fuera de muestra, igual que en las pruebas
anteriores.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_drawdown_10pct_63activos.py
    python scripts/backtest_drawdown_10pct_63activos.py --inicio 2018-01-01
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings

UMBRAL_ANOMALIA = 15.0
VENTANA_MAXIMO = 20
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _cargar_datos_diarios(symbol, fecha_inicio):
    try:
        data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    except Exception:
        return None
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    # Excluir velas fantasma: volumen cero (días sin negociación real, como
    # festivos, que Yahoo Finance rellena con un valor plano en vez de omitir)
    data = data[data["Volume"] > 0]
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_drawdown(data, ventana_maximo, umbral_drawdown):
    maximo_reciente = data["Close"].rolling(ventana_maximo).max().shift(1)
    drawdown_pct = -((data["Close"] - maximo_reciente) / maximo_reciente * 100)

    cruces = []
    for i in range(ventana_maximo + 1, len(data)):
        dd_hoy = drawdown_pct.iloc[i]
        dd_ayer = drawdown_pct.iloc[i - 1]

        if dd_hoy != dd_hoy or dd_ayer != dd_ayer:
            continue

        if dd_ayer < umbral_drawdown and dd_hoy >= umbral_drawdown:
            cruces.append(i)

    return cruces


def _simular_trailing_stop(data, idx_entrada, entrada_precio, stop_inicial_pct, objetivo_inicial_pct):
    stop = entrada_precio * (1 - stop_inicial_pct)
    objetivo = entrada_precio * (1 + objetivo_inicial_pct)

    n = len(data)

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]

        if low <= stop:
            return float(stop), data.index[i]

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + INCREMENTO_PCT)

    return float(data["Close"].iloc[-1]), data.index[-1]


@dataclass
class Operacion:
    symbol: str
    entrada_fecha: object
    entrada_precio: float
    variacion_pct: float


def _simular_operaciones(symbol, data, indices_entrada, stop_inicial_pct, objetivo_inicial_pct):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        salida_precio, salida_fecha = _simular_trailing_stop(
            data, idx_entrada, entrada_precio, stop_inicial_pct, objetivo_inicial_pct
        )

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        operaciones.append(Operacion(symbol, entrada_fecha, entrada_precio, variacion_pct))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(symbol, data, cantidad, semilla, minimo_idx, stop_inicial_pct, objetivo_inicial_pct):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(symbol, data, sorted(set(indices_random)), stop_inicial_pct, objetivo_inicial_pct)


def correr(fecha_inicio, umbral_drawdown, stop_inicial_pct, objetivo_inicial_pct):
    activos = Settings.todos_los_activos()

    print(f"Universo: {len(activos)} activos (BVC + internacional + ETF + cripto)")
    print(f"Señal: cruce de drawdown a -{umbral_drawdown:.0f}% o más desde el máximo de {VENTANA_MAXIMO} días")
    print(f"Salida: trailing stop (-{stop_inicial_pct*100:.1f}%/+{objetivo_inicial_pct*100:.1f}%/"
          f"+{INCREMENTO_PCT*100:.0f}%)")
    print()

    todas_calib = []
    todas_valid = []
    datos_por_symbol = {}
    omitidos = []

    for symbol in activos:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < VENTANA_MAXIMO + 20:
            omitidos.append(symbol)
            continue

        data = _filtrar_anomalias(data)
        if len(data) < VENTANA_MAXIMO + 20:
            omitidos.append(symbol)
            continue

        datos_por_symbol[symbol] = data

        cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, umbral_drawdown)
        operaciones = _simular_operaciones(symbol, data, cruces, stop_inicial_pct, objetivo_inicial_pct)

        if not operaciones:
            continue

        punto_medio = len(operaciones) // 2
        calib = operaciones[:punto_medio]
        valid = operaciones[punto_medio:]

        neto_symbol = sum(_calcular_dinero(op.variacion_pct) for op in operaciones)
        print(f"{symbol:14} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP "
              f"(calib={len(calib)}, valid={len(valid)})")

        todas_calib.extend(calib)
        todas_valid.extend(valid)

    print()
    if omitidos:
        print(f"Omitidos por falta de datos ({len(omitidos)}): {', '.join(omitidos)}")
        print()

    print("=" * 100)
    print(f"CALIBRACIÓN: {len(todas_calib)} operaciones")
    print("=" * 100)
    if todas_calib:
        neto_calib = sum(_calcular_dinero(op.variacion_pct) for op in todas_calib)
        ganaron_calib = sum(1 for op in todas_calib if _calcular_dinero(op.variacion_pct) > 0)
        print(f"Neto total: ${neto_calib:+,.0f} COP | Ganadoras: {ganaron_calib}/{len(todas_calib)} "
              f"({ganaron_calib/len(todas_calib)*100:.1f}%)")

    print()
    print("=" * 100)
    print(f"VALIDACIÓN FUERA DE MUESTRA: {len(todas_valid)} operaciones")
    print("=" * 100)

    if todas_valid:
        neto_valid = sum(_calcular_dinero(op.variacion_pct) for op in todas_valid)
        ganaron_valid = sum(1 for op in todas_valid if _calcular_dinero(op.variacion_pct) > 0)
        print(f"Neto total: ${neto_valid:+,.0f} COP | Ganadoras: {ganaron_valid}/{len(todas_valid)} "
              f"({ganaron_valid/len(todas_valid)*100:.1f}%)")

        n_total = 0
        neto_random_total = 0.0
        for symbol, data in datos_por_symbol.items():
            cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, umbral_drawdown)
            operaciones = _simular_operaciones(symbol, data, cruces, stop_inicial_pct, objetivo_inicial_pct)
            punto_medio = len(operaciones) // 2
            n_valid_symbol = len(operaciones) - punto_medio

            aleatorias = _generar_aleatorias(
                symbol, data, n_valid_symbol, hash(symbol) % 10000, VENTANA_MAXIMO,
                stop_inicial_pct, objetivo_inicial_pct
            )
            neto_random_total += sum(_calcular_dinero(op.variacion_pct) for op in aleatorias)
            n_total += len(aleatorias)

        print(f"Grupo de control aleatorio (mismo tamaño): {n_total} operaciones | "
              f"neto ${neto_random_total:+,.0f} COP")
    else:
        print("Sin operaciones en validación.")

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2018-01-01")
    parser.add_argument("--umbral_drawdown", type=float, default=10.0)
    parser.add_argument("--stop", type=float, default=0.05)
    parser.add_argument("--objetivo", type=float, default=0.08)
    args = parser.parse_args()

    correr(args.inicio, args.umbral_drawdown, args.stop, args.objetivo)