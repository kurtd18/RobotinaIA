"""
Aplica el mismo sistema de "drawdown -10% + trailing stop" (encontrado y
validado en BVC e internacional) a las criptomonedas principales, usando
velas de 6 HORAS (no días completos) y solo datos de 2026.

Señal de entrada: el momento exacto en que el drawdown desde el máximo de
las últimas 20 velas de 6 horas (equivalente a 5 días de calendario)
cruza a -10% o más.

Salida: trailing stop real (stop inicial -5%, objetivo inicial +8%,
incrementos de +1% - mismos parámetros que dieron el mejor resultado en
BVC).

Dinero: desembolso $5,000,000 COP por operación, comisión $7,000 COP por
lado.

Calibración/validación fuera de muestra, y grupo de control aleatorio,
igual que en las pruebas anteriores.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_drawdown_cripto_6h.py
    python scripts/backtest_drawdown_cripto_6h.py --sin_detalle
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

CRIPTOS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "TRXUSDT", "DOGEUSDT", "ZECUSDT", "XLMUSDT",
]

VENTANA_MAXIMO = 20  # velas de 6h -> equivalente a 5 días de calendario
UMBRAL_DRAWDOWN = 10.0
INCREMENTO_PCT = 0.01
STOP_INICIAL_PCT = 0.05
OBJETIVO_INICIAL_PCT = 0.08

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

FECHA_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    data = data[data["Volume"] > 0]
    return data


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


def _simular_trailing_stop(data, idx_entrada, entrada_precio):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + OBJETIVO_INICIAL_PCT)

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
    salida_fecha: object
    salida_precio: float
    variacion_pct: float
    neto: float


def _simular_operaciones(symbol, data, indices_entrada):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        salida_precio, salida_fecha = _simular_trailing_stop(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)

        operaciones.append(Operacion(
            symbol=symbol, entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            salida_fecha=salida_fecha, salida_precio=salida_precio,
            variacion_pct=variacion_pct, neto=neto,
        ))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(symbol, data, cantidad, semilla, minimo_idx):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(symbol, data, sorted(set(indices_random)))


def correr(mostrar_detalle):
    print(f"Criptos: {len(CRIPTOS)} | Velas de 6 horas | Datos desde {FECHA_INICIO.strftime('%Y-%m-%d')}")
    print(f"Señal: cruce de drawdown a -{UMBRAL_DRAWDOWN:.0f}% o más desde el máximo de "
          f"{VENTANA_MAXIMO} velas de 6h (~{VENTANA_MAXIMO*6//24} días)")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}%/+{OBJETIVO_INICIAL_PCT*100:.1f}%/"
          f"+{INCREMENTO_PCT*100:.0f}%)")
    print()

    todas_calib = []
    todas_valid = []
    datos_por_symbol = {}

    for symbol in CRIPTOS:
        print(f"Descargando {symbol}...")
        try:
            data = obtener_klines(symbol, "6h", FECHA_INICIO)
        except Exception as e:
            print(f"  {symbol}: error ({type(e).__name__}), se omite")
            continue

        if data is None or len(data) < VENTANA_MAXIMO + 20:
            print(f"  {symbol}: sin datos suficientes")
            continue

        data = _limpiar_datos(data)
        datos_por_symbol[symbol] = data

        cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, UMBRAL_DRAWDOWN)
        operaciones = _simular_operaciones(symbol, data, cruces)

        if mostrar_detalle and operaciones:
            for op in operaciones:
                print(f"    {op.entrada_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.entrada_precio:,.4f} -> "
                      f"{op.salida_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.salida_precio:,.4f} | "
                      f"{op.variacion_pct:+.2f}% | neto {op.neto:+,.0f} COP")

        punto_medio = len(operaciones) // 2
        calib = operaciones[:punto_medio]
        valid = operaciones[punto_medio:]

        neto_symbol = sum(op.neto for op in operaciones)
        print(f"  {symbol:10} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP "
              f"(calib={len(calib)}, valid={len(valid)}) | {len(data)} velas")

        todas_calib.extend(calib)
        todas_valid.extend(valid)

    print()
    print("=" * 100)
    print(f"CALIBRACIÓN: {len(todas_calib)} operaciones")
    print("=" * 100)
    if todas_calib:
        neto_calib = sum(op.neto for op in todas_calib)
        ganaron_calib = sum(1 for op in todas_calib if op.neto > 0)
        print(f"Neto total: ${neto_calib:+,.0f} COP | Ganadoras: {ganaron_calib}/{len(todas_calib)} "
              f"({ganaron_calib/len(todas_calib)*100:.1f}%)")

    print()
    print("=" * 100)
    print(f"VALIDACIÓN FUERA DE MUESTRA: {len(todas_valid)} operaciones")
    print("=" * 100)

    if todas_valid:
        neto_valid = sum(op.neto for op in todas_valid)
        ganaron_valid = sum(1 for op in todas_valid if op.neto > 0)
        print(f"Neto total: ${neto_valid:+,.0f} COP | Ganadoras: {ganaron_valid}/{len(todas_valid)} "
              f"({ganaron_valid/len(todas_valid)*100:.1f}%)")

        n_total = 0
        neto_random_total = 0.0
        for symbol, data in datos_por_symbol.items():
            cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, UMBRAL_DRAWDOWN)
            operaciones = _simular_operaciones(symbol, data, cruces)
            punto_medio = len(operaciones) // 2
            n_valid_symbol = len(operaciones) - punto_medio

            aleatorias = _generar_aleatorias(symbol, data, n_valid_symbol, hash(symbol) % 10000, VENTANA_MAXIMO)
            neto_random_total += sum(op.neto for op in aleatorias)
            n_total += len(aleatorias)

        print(f"Grupo de control aleatorio (mismo tamaño): {n_total} operaciones | "
              f"neto ${neto_random_total:+,.0f} COP")

        if len(todas_valid) < 30:
            print("⚠️  Muestra menor a 30 - resultado indicativo, no concluyente todavía.")
    else:
        print("Sin operaciones en validación.")

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin_detalle", action="store_true", help="No imprimir el detalle de cada operación")
    args = parser.parse_args()

    correr(not args.sin_detalle)