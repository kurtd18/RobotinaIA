"""
RSI(2) de Larry Connors - estrategia documentada en su libro "Short Term
Trading Strategies That Work" (Connors & Alvarez, 2008).

Señal de entrada: el momento en que el RSI de período 2 CRUZA por debajo
de 5, mientras el precio está por encima de su media móvil de 200 días
(el filtro de tendencia alcista de largo plazo - Connors solo opera a
favor de la tendencia principal, no en cualquier caída).

Señal de salida: el RSI(2) cruza por encima de 70 (o el precio cae por
debajo de la SMA200, lo que ocurra primero - se sale del filtro de
tendencia).

Money: $5,000,000 COP por operación, comisión $7,000 COP por lado (igual
que el resto de la sesión).

Calibración/validación fuera de muestra, y grupo de control aleatorio.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_rsi2_connors.py
    python scripts/backtest_rsi2_connors.py --todos_63
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas_ta as ta
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS_BVC_10 = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

FECHA_INICIO_DEFECTO = "2023-01-01"
UMBRAL_ANOMALIA = 15.0

RSI_PERIODO = 2
RSI_ENTRADA = 5.0
RSI_SALIDA = 70.0
SMA_PERIODO = 200

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


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    data = data[data["Volume"] > 0]
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_entrada(data):
    """Devuelve los índices donde el RSI(2) CRUZA por debajo de 5,
    mientras el precio está por encima de la SMA200 (el momento exacto,
    no cada día que se mantiene en esa zona)."""

    close = data["Close"]
    rsi2 = ta.rsi(close, length=RSI_PERIODO)
    sma200 = ta.sma(close, length=SMA_PERIODO)

    if rsi2 is None or sma200 is None:
        return [], None, None

    cruces = []
    for i in range(SMA_PERIODO + 2, len(data)):
        rsi_hoy = rsi2.iloc[i]
        rsi_ayer = rsi2.iloc[i - 1]
        sma_hoy = sma200.iloc[i]
        precio_hoy = close.iloc[i]

        if rsi_hoy != rsi_hoy or rsi_ayer != rsi_ayer or sma_hoy != sma_hoy:
            continue

        tendencia_alcista = precio_hoy > sma_hoy
        cruzo_a_sobreventa = rsi_ayer >= RSI_ENTRADA and rsi_hoy < RSI_ENTRADA

        if tendencia_alcista and cruzo_a_sobreventa:
            cruces.append(i)

    return cruces, rsi2, sma200


def _simular_salida(data, rsi2, sma200, idx_entrada, entrada_precio):
    """Sale cuando el RSI(2) cruza por encima de 70, o si el precio cae
    por debajo de la SMA200 (se sale del filtro de tendencia), lo que
    ocurra primero."""

    n = len(data)
    close = data["Close"]

    for i in range(idx_entrada + 1, n):
        rsi_hoy = rsi2.iloc[i]
        precio_hoy = close.iloc[i]
        sma_hoy = sma200.iloc[i]

        if rsi_hoy != rsi_hoy or sma_hoy != sma_hoy:
            continue

        if rsi_hoy > RSI_SALIDA or precio_hoy < sma_hoy:
            return float(precio_hoy), data.index[i]

    precio_final = float(close.iloc[-1])
    return precio_final, data.index[-1]


@dataclass
class Operacion:
    symbol: str
    entrada_fecha: object
    entrada_precio: float
    salida_fecha: object
    salida_precio: float
    variacion_pct: float
    neto: float


def _simular_operaciones(symbol, data, indices_entrada, rsi2, sma200):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        salida_precio, salida_fecha = _simular_salida(data, rsi2, sma200, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)

        operaciones.append(Operacion(
            symbol, entrada_fecha, entrada_precio, salida_fecha, salida_precio, variacion_pct, neto
        ))
        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(symbol, data, rsi2, sma200, cantidad, semilla, minimo_idx):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(symbol, data, sorted(set(indices_random)), rsi2, sma200)


def correr(activos, fecha_inicio):
    print(f"RSI(2) de Connors: {len(activos)} activos, desde {fecha_inicio}")
    print(f"Entrada: precio > SMA{SMA_PERIODO} y RSI({RSI_PERIODO}) cruza debajo de {RSI_ENTRADA:.0f}")
    print(f"Salida: RSI({RSI_PERIODO}) cruza sobre {RSI_SALIDA:.0f}, o precio cae bajo SMA{SMA_PERIODO}")
    print()

    todas_calib = []
    todas_valid = []
    datos_por_symbol = {}

    for symbol in activos:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < SMA_PERIODO + 30:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _limpiar_datos(data)
        cruces, rsi2, sma200 = _detectar_cruces_entrada(data)
        if rsi2 is None:
            print(f"{symbol}: no se pudo calcular RSI/SMA, se omite")
            continue

        datos_por_symbol[symbol] = (data, rsi2, sma200)

        operaciones = _simular_operaciones(symbol, data, cruces, rsi2, sma200)

        punto_medio = len(operaciones) // 2
        calib = operaciones[:punto_medio]
        valid = operaciones[punto_medio:]

        neto_symbol = sum(op.neto for op in operaciones)
        print(f"{symbol:14} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP "
              f"(calib={len(calib)}, valid={len(valid)})")

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
        for symbol, (data, rsi2, sma200) in datos_por_symbol.items():
            cruces, _, _ = _detectar_cruces_entrada(data)
            operaciones = _simular_operaciones(symbol, data, cruces, rsi2, sma200)
            punto_medio = len(operaciones) // 2
            n_valid_symbol = len(operaciones) - punto_medio

            aleatorias = _generar_aleatorias(
                symbol, data, rsi2, sma200, n_valid_symbol, hash(symbol) % 10000, SMA_PERIODO
            )
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
    parser.add_argument("--todos_63", action="store_true")
    parser.add_argument("--inicio", type=str, default=FECHA_INICIO_DEFECTO,
                         help="Fecha de inicio, formato YYYY-MM-DD")
    args = parser.parse_args()

    if args.todos_63:
        from app.core.settings import Settings
        _CRIPTOS_A_EXCLUIR = {"BTC-USD", "ETH-USD", "SOL-USD"}
        activos = [a for a in Settings.todos_los_activos() if a not in _CRIPTOS_A_EXCLUIR]
    else:
        activos = ACTIVOS_BVC_10

    correr(activos, args.inicio)