"""
Backtest de la estrategia "racha verde" para 5 criptomonedas principales,
en velas de 15 minutos, últimos 3 meses, usando datos de Binance.

Lógica de entrada (misma idea validada con BVC, aplicada a velas de 15
minutos en vez de días):
  1. Una vela cierra en rojo (cierre < cierre de la vela anterior)
  2. La vela siguiente cierra en verde (cierre > cierre de la vela roja)
     -> se CONFIRMA la señal y se compra al cierre de esa vela verde

Salida: mismo trailing stop real (stop inicial -1.5%, objetivo inicial
+3%, incrementos de +1%).

Dinero: mismo método validado (desembolso $5,000,000 COP, comisión
$7,000 COP por lado, descontada del desembolso/lo recibido al vender).

Cripto opera 24/7, así que a diferencia de la BVC no hay huecos de
horario de mercado que considerar.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_racha_verde_cripto_15m.py
    python scripts/backtest_racha_verde_cripto_15m.py --meses 3
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

CRIPTOS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT"]

STOP_INICIAL_PCT = 0.015
OBJETIVO_INICIAL_PCT = 0.03
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


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
    salida_fecha: object
    salida_precio: float
    resultado: str
    variacion_pct: float


def _analizar_symbol(data):
    cierres = data["Close"].values
    fechas = data.index
    n = len(cierres)

    operaciones = []
    en_posicion_hasta_idx = -1

    i = 1
    while i < n:
        es_rojo = cierres[i] < cierres[i - 1]

        if not es_rojo or i + 1 >= n:
            i += 1
            continue

        es_verde = cierres[i + 1] > cierres[i]
        if not es_verde:
            i += 1
            continue

        idx_entrada = i + 1
        if idx_entrada <= en_posicion_hasta_idx:
            i += 1
            continue

        entrada_precio = float(cierres[idx_entrada])
        entrada_fecha = fechas[idx_entrada]

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100

        operaciones.append(Operacion(
            entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            salida_fecha=salida_fecha, salida_precio=salida_precio,
            resultado=resultado, variacion_pct=variacion_pct,
        ))

        en_posicion_hasta_idx = idx_salida
        i = idx_salida + 1

    return operaciones


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def correr(meses):
    fecha_inicio = datetime.now(timezone.utc) - timedelta(days=meses * 30)

    print(f"Período: últimos {meses} meses (desde {fecha_inicio.strftime('%Y-%m-%d')})")
    print(f"Velas de 15 minutos | Desembolso: ${DESEMBOLSO_TOTAL:,.0f} COP | Comisión: ${COMISION:,.0f} COP/lado")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}% inicial, "
          f"+{OBJETIVO_INICIAL_PCT*100:.0f}% objetivo inicial, +{INCREMENTO_PCT*100:.0f}% incrementos)")
    print()

    neto_total_general = 0.0
    operaciones_total_general = 0
    ganadoras_general = 0
    perdedoras_general = 0

    for symbol in CRIPTOS:
        print("=" * 100)
        print(symbol)
        print("=" * 100)

        try:
            data = obtener_klines(symbol, "15m", fecha_inicio)
        except Exception as e:
            print(f"  Error irrecuperable ({type(e).__name__}), se omite.")
            print()
            continue

        if data is None or len(data) < 20:
            print("  Sin datos suficientes.")
            print()
            continue

        print(f"  Rango: {data.index[0].strftime('%Y-%m-%d')} a {data.index[-1].strftime('%Y-%m-%d')} "
              f"({len(data)} velas)")

        operaciones = _analizar_symbol(data)

        if not operaciones:
            print("  No se generaron operaciones.")
            print()
            continue

        neto_symbol = 0.0
        ganaron = 0
        perdieron = 0

        for op in operaciones:
            neto = _calcular_dinero(op.variacion_pct)
            neto_symbol += neto

            if neto > 0:
                ganaron += 1
            else:
                perdieron += 1

            print(f"  Compra {op.entrada_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.entrada_precio:,.4f}  ->  "
                  f"Venta {op.salida_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.salida_precio:,.4f} | "
                  f"{op.resultado:12} | {op.variacion_pct:+.2f}% | neto {neto:+,.0f} COP")

        print("-" * 100)
        print(f"  Operaciones: {len(operaciones)} (netas positivas={ganaron} negativas={perdieron})")
        print(f"  Resultado neto de {symbol}: ${neto_symbol:+,.0f} COP")
        print()

        neto_total_general += neto_symbol
        operaciones_total_general += len(operaciones)
        ganadoras_general += ganaron
        perdedoras_general += perdieron

    print("=" * 100)
    print("RESUMEN GENERAL (las 5 criptos juntas)")
    print("=" * 100)
    print(f"Total de operaciones: {operaciones_total_general} "
          f"(netas positivas={ganadoras_general} negativas={perdedoras_general})")
    print(f"Capital total desembolsado: ${operaciones_total_general * DESEMBOLSO_TOTAL:,.0f} COP")
    print(f"Resultado neto total: ${neto_total_general:+,.0f} COP")
    if operaciones_total_general < 30:
        print("⚠️  Muestra menor a 30 operaciones - no es suficiente para conclusiones firmes.")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--meses", type=int, default=3)
    args = parser.parse_args()

    correr(args.meses)