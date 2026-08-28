"""
RSI(2) de Connors y 5 variantes, todas en un solo script - sobre las 9
criptos principales, velas de 3 horas (vía Binance, mercado 24/7).

NOTA: se usa cripto en vez de acciones porque las velas de 3h en
acciones (BVC/EE.UU., que solo cotizan ~6.5h al día) chocarían con el
límite de 60 días que tiene Yahoo Finance para datos intradía - no
alcanzaría para calcular una SMA200. Binance no tiene ese límite.

Variantes probadas (cada una cambia UNA sola pieza respecto a la base,
para poder ver qué parte aporta):

  1. BASE:              RSI(2) <5  | SMA200 | sale con RSI(2) >70
  2. ENTRADA_LAXA:       RSI(2) <10 | SMA200 | sale con RSI(2) >70
  3. SALIDA_RAPIDA:      RSI(2) <5  | SMA200 | sale con RSI(2) >60
  4. SALIDA_SIMPLE_50:   RSI(2) <5  | SMA200 | sale con RSI(2) cruza sobre 50
  5. RSI_PERIODO_3:      RSI(3) <5  | SMA200 | sale con RSI(3) >70
  6. SMA_CORTA_100:      RSI(2) <5  | SMA100 | sale con RSI(2) >70

Todas comparten la misma salida adicional: si el precio cae bajo la SMA
del filtro de tendencia, se sale ahí también (se sale del filtro).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_rsi2_variantes_cripto_3h.py
    python scripts/backtest_rsi2_variantes_cripto_3h.py --inicio 2023-01-01
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas_ta as ta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

CRIPTOS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "TRXUSDT", "DOGEUSDT", "ZECUSDT", "XLMUSDT",
]

FECHA_INICIO_DEFECTO = "2022-01-01"

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

VARIANTES = [
    {"nombre": "1. BASE",            "rsi_periodo": 2, "rsi_entrada": 5.0,  "sma_periodo": 200, "salida": "sobrecompra", "rsi_salida": 70.0},
    {"nombre": "2. ENTRADA_LAXA",    "rsi_periodo": 2, "rsi_entrada": 10.0, "sma_periodo": 200, "salida": "sobrecompra", "rsi_salida": 70.0},
    {"nombre": "3. SALIDA_RAPIDA",   "rsi_periodo": 2, "rsi_entrada": 5.0,  "sma_periodo": 200, "salida": "sobrecompra", "rsi_salida": 60.0},
    {"nombre": "4. SALIDA_SIMPLE_50","rsi_periodo": 2, "rsi_entrada": 5.0,  "sma_periodo": 200, "salida": "cruce_50",    "rsi_salida": 50.0},
    {"nombre": "5. RSI_PERIODO_3",   "rsi_periodo": 3, "rsi_entrada": 5.0,  "sma_periodo": 200, "salida": "sobrecompra", "rsi_salida": 70.0},
    {"nombre": "6. SMA_CORTA_100",   "rsi_periodo": 2, "rsi_entrada": 5.0,  "sma_periodo": 100, "salida": "sobrecompra", "rsi_salida": 70.0},
]


def _obtener_klines_3h(symbol, fecha_inicio):
    """Binance no tiene un intervalo nativo de 3 horas (los que sí tiene
    son 1h, 2h, 4h, 6h, 8h, 12h...) - se descarga en velas de 1h y se
    combinan en grupos de 3 para armar velas de 3h reales (Open=la
    primera, High=el máximo, Low=el mínimo, Close=la última, Volume=la
    suma de las 3)."""

    data_1h = obtener_klines(symbol, "1h", fecha_inicio)
    if data_1h is None or data_1h.empty:
        return None

    data_3h = data_1h.resample("3h").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    })
    return data_3h.dropna(subset=["Open", "High", "Low", "Close"])


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    return data[data["Volume"] > 0]


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_entrada(data, rsi_periodo, rsi_entrada, sma_periodo):
    close = data["Close"]
    rsi = ta.rsi(close, length=rsi_periodo)
    sma = ta.sma(close, length=sma_periodo)

    if rsi is None or sma is None:
        return [], None, None

    cruces = []
    for i in range(sma_periodo + 2, len(data)):
        rsi_hoy = rsi.iloc[i]
        rsi_ayer = rsi.iloc[i - 1]
        sma_hoy = sma.iloc[i]
        precio_hoy = close.iloc[i]

        if rsi_hoy != rsi_hoy or rsi_ayer != rsi_ayer or sma_hoy != sma_hoy:
            continue

        tendencia_alcista = precio_hoy > sma_hoy
        cruzo_a_sobreventa = rsi_ayer >= rsi_entrada and rsi_hoy < rsi_entrada

        if tendencia_alcista and cruzo_a_sobreventa:
            cruces.append(i)

    return cruces, rsi, sma


def _simular_salida(data, rsi, sma, idx_entrada, tipo_salida, rsi_salida):
    n = len(data)
    close = data["Close"]

    for i in range(idx_entrada + 1, n):
        rsi_hoy = rsi.iloc[i]
        rsi_ayer = rsi.iloc[i - 1]
        precio_hoy = close.iloc[i]
        sma_hoy = sma.iloc[i]

        if rsi_hoy != rsi_hoy or rsi_ayer != rsi_ayer or sma_hoy != sma_hoy:
            continue

        # Salida por perder el filtro de tendencia (siempre activa)
        if precio_hoy < sma_hoy:
            return float(precio_hoy), data.index[i]

        if tipo_salida == "sobrecompra":
            if rsi_hoy > rsi_salida:
                return float(precio_hoy), data.index[i]
        elif tipo_salida == "cruce_50":
            if rsi_ayer < rsi_salida and rsi_hoy >= rsi_salida:
                return float(precio_hoy), data.index[i]

    return float(close.iloc[-1]), data.index[-1]


@dataclass
class Operacion:
    symbol: str
    entrada_fecha: object
    entrada_precio: float
    variacion_pct: float
    neto: float


def _simular_operaciones(symbol, data, indices_entrada, rsi, sma, tipo_salida, rsi_salida):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        salida_precio, salida_fecha = _simular_salida(data, rsi, sma, idx_entrada, tipo_salida, rsi_salida)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)

        operaciones.append(Operacion(symbol, entrada_fecha, entrada_precio, variacion_pct, neto))
        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(symbol, data, rsi, sma, tipo_salida, rsi_salida, cantidad, semilla, minimo_idx):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(symbol, data, sorted(set(indices_random)), rsi, sma, tipo_salida, rsi_salida)


def correr(fecha_inicio_str):
    fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print(f"RSI(2) de Connors y variantes - Cripto, velas de 3h, desde {fecha_inicio_str}")
    print()

    print("Descargando datos de las 9 criptos (una sola vez, se reutilizan para todas las variantes)...")
    datos_por_symbol = {}
    for symbol in CRIPTOS:
        try:
            data = _obtener_klines_3h(symbol, fecha_inicio)
        except Exception as e:
            print(f"  {symbol}: error ({type(e).__name__}), se omite")
            continue
        if data is None or len(data) < 230:
            print(f"  {symbol}: sin datos suficientes")
            continue
        datos_por_symbol[symbol] = _limpiar_datos(data)
    print(f"Listo: {len(datos_por_symbol)} criptos con datos.")
    print()

    for variante in VARIANTES:
        print("=" * 100)
        print(f"VARIANTE: {variante['nombre']} "
              f"(RSI({variante['rsi_periodo']})<{variante['rsi_entrada']:.0f}, SMA{variante['sma_periodo']}, "
              f"salida={variante['salida']}({variante['rsi_salida']:.0f}))")
        print("=" * 100)

        todas_calib = []
        todas_valid = []

        for symbol, data in datos_por_symbol.items():
            if len(data) < variante["sma_periodo"] + 30:
                continue

            cruces, rsi, sma = _detectar_cruces_entrada(
                data, variante["rsi_periodo"], variante["rsi_entrada"], variante["sma_periodo"]
            )
            if rsi is None:
                continue

            operaciones = _simular_operaciones(
                symbol, data, cruces, rsi, sma, variante["salida"], variante["rsi_salida"]
            )

            punto_medio = len(operaciones) // 2
            todas_calib.extend(operaciones[:punto_medio])
            todas_valid.extend(operaciones[punto_medio:])

        neto_calib = sum(op.neto for op in todas_calib)
        neto_valid = sum(op.neto for op in todas_valid)
        ganaron_valid = sum(1 for op in todas_valid if op.neto > 0)

        print(f"Calibración: {len(todas_calib)} ops | neto ${neto_calib:+,.0f} COP")
        print(f"Validación:  {len(todas_valid)} ops | neto ${neto_valid:+,.0f} COP | "
              f"ganadoras {ganaron_valid}/{len(todas_valid) or 1} "
              f"({ganaron_valid/len(todas_valid)*100 if todas_valid else 0:.1f}%)")

        if todas_valid:
            n_total = 0
            neto_random_total = 0.0
            for symbol, data in datos_por_symbol.items():
                if len(data) < variante["sma_periodo"] + 30:
                    continue
                cruces, rsi, sma = _detectar_cruces_entrada(
                    data, variante["rsi_periodo"], variante["rsi_entrada"], variante["sma_periodo"]
                )
                if rsi is None:
                    continue
                operaciones = _simular_operaciones(
                    symbol, data, cruces, rsi, sma, variante["salida"], variante["rsi_salida"]
                )
                punto_medio = len(operaciones) // 2
                n_valid_symbol = len(operaciones) - punto_medio

                aleatorias = _generar_aleatorias(
                    symbol, data, rsi, sma, variante["salida"], variante["rsi_salida"],
                    n_valid_symbol, hash(symbol + variante["nombre"]) % 10000, variante["sma_periodo"]
                )
                neto_random_total += sum(op.neto for op in aleatorias)
                n_total += len(aleatorias)

            print(f"Control aleatorio: {n_total} ops | neto ${neto_random_total:+,.0f} COP")

            if len(todas_valid) < 30:
                print("⚠️  Muestra menor a 30 - indicativo, no concluyente.")

        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default=FECHA_INICIO_DEFECTO)
    args = parser.parse_args()

    correr(args.inicio)