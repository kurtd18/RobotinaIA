"""
Igual que backtest_drawdown_cripto_6h.py, pero con un universo ampliado
de 50 criptomonedas (elegidas del top de capitalización de mercado,
excluyendo stablecoins, tokens envueltos/wrapped y derivados de staking).

Algunas de estas 50 pueden no estar disponibles como par spot en Binance
(ya vimos esto antes con HYPE y XMR) - el script las salta
automáticamente sin detener el proceso.

Misma señal y salida ya validadas: drawdown -10% desde el máximo de 20
velas de 6h, trailing stop -5%/+8%/+1%.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_drawdown_cripto_50.py
    python scripts/backtest_drawdown_cripto_50.py --sin_detalle
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
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "TRXUSDT",
    "DOGEUSDT", "ADAUSDT", "BCHUSDT", "LINKUSDT", "XLMUSDT", "CROUSDT",
    "SUIUSDT", "AVAXUSDT", "SHIBUSDT", "LTCUSDT", "DOTUSDT", "HBARUSDT",
    "UNIUSDT", "AAVEUSDT", "NEARUSDT", "APTUSDT", "ICPUSDT", "ETCUSDT",
    "PEPEUSDT", "TAOUSDT", "RENDERUSDT", "ONDOUSDT", "FETUSDT", "ARBUSDT",
    "ATOMUSDT", "FILUSDT", "OPUSDT", "IMXUSDT", "INJUSDT", "VETUSDT",
    "ALGOUSDT", "GRTUSDT", "SEIUSDT", "STXUSDT", "THETAUSDT", "RUNEUSDT",
    "MKRUSDT", "QNTUSDT", "LDOUSDT", "TIAUSDT", "WLDUSDT", "JUPUSDT",
    "HYPEUSDT", "XMRUSDT",
]

VENTANA_MAXIMO = 20
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


def correr(mostrar_detalle, filtrar_mes=None):
    print(f"Criptos: {len(CRIPTOS)} | Velas de 6 horas | Datos desde {FECHA_INICIO.strftime('%Y-%m-%d')}")
    print(f"Señal: drawdown -{UMBRAL_DRAWDOWN:.0f}% desde el máximo de {VENTANA_MAXIMO} velas de 6h")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}%/+{OBJETIVO_INICIAL_PCT*100:.1f}%/"
          f"+{INCREMENTO_PCT*100:.0f}%)")
    if filtrar_mes:
        print(f"Mostrando detalle solo del mes: {filtrar_mes}")
    print()

    todas_las_operaciones = []
    omitidos = []

    for symbol in CRIPTOS:
        try:
            data = obtener_klines(symbol, "6h", FECHA_INICIO)
        except Exception as e:
            omitidos.append(f"{symbol} ({type(e).__name__})")
            continue

        if data is None or len(data) < VENTANA_MAXIMO + 20:
            omitidos.append(f"{symbol} (sin datos)")
            continue

        data = _limpiar_datos(data)
        cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, UMBRAL_DRAWDOWN)
        operaciones = _simular_operaciones(symbol, data, cruces)
        todas_las_operaciones.extend(operaciones)

        neto_symbol = sum(op.neto for op in operaciones)
        print(f"{symbol:10} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP")

    print()
    if omitidos:
        print(f"Omitidas ({len(omitidos)}): {', '.join(omitidos)}")
        print()

    if filtrar_mes:
        ops_mes = [op for op in todas_las_operaciones if op.entrada_fecha.strftime("%Y-%m") == filtrar_mes]

        print("=" * 100)
        print(f"DETALLE DEL MES {filtrar_mes}")
        print("=" * 100)

        for op in sorted(ops_mes, key=lambda o: o.entrada_fecha):
            print(f"  {op.symbol:10} {op.entrada_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.entrada_precio:,.4f} -> "
                  f"{op.salida_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.salida_precio:,.4f} | "
                  f"{op.variacion_pct:+.2f}% | neto {op.neto:+,.0f} COP")

        neto_mes = sum(op.neto for op in ops_mes)
        ganaron = sum(1 for op in ops_mes if op.neto > 0)
        print("-" * 100)
        print(f"Total del mes: {len(ops_mes)} operaciones | ganadoras {ganaron}/{len(ops_mes)} "
              f"({ganaron/len(ops_mes)*100:.1f}%)" if ops_mes else "Sin operaciones este mes")
        print(f"Neto del mes: ${neto_mes:+,.0f} COP")
        print("=" * 100)

    print()
    print("=" * 100)
    print("RESUMEN GENERAL (todo el período)")
    print("=" * 100)
    neto_total = sum(op.neto for op in todas_las_operaciones)
    ganaron_total = sum(1 for op in todas_las_operaciones if op.neto > 0)
    print(f"Total: {len(todas_las_operaciones)} operaciones | ganadoras {ganaron_total}/{len(todas_las_operaciones)}")
    print(f"Neto total: ${neto_total:+,.0f} COP")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin_detalle", action="store_true")
    parser.add_argument("--mes", type=str, default="2026-03", help="Mes a detallar, formato YYYY-MM")
    args = parser.parse_args()

    correr(True, filtrar_mes=args.mes)