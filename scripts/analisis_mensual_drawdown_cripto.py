"""
Desglosa mes a mes el resultado de la señal "drawdown -10% + trailing
stop" sobre las 9 criptos (velas de 6 horas, 2026), para identificar en
qué período específico está la diferencia entre calibración y
validación que se vio en el backtest general.

Reutiliza exactamente la misma lógica ya validada de
backtest_drawdown_cripto_6h.py - solo cambia cómo se presenta el
resultado (agrupado por mes, en vez de calibración/validación).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_mensual_drawdown_cripto.py
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines
from scripts.backtest_drawdown_cripto_6h import (
    CRIPTOS, VENTANA_MAXIMO, UMBRAL_DRAWDOWN, FECHA_INICIO,
    _limpiar_datos, _detectar_cruces_drawdown, _simular_operaciones,
)


def correr():
    todas_las_operaciones = []

    for symbol in CRIPTOS:
        print(f"Procesando {symbol}...")
        try:
            data = obtener_klines(symbol, "6h", FECHA_INICIO)
        except Exception as e:
            print(f"  {symbol}: error ({type(e).__name__}), se omite")
            continue

        if data is None or len(data) < VENTANA_MAXIMO + 20:
            continue

        data = _limpiar_datos(data)
        cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, UMBRAL_DRAWDOWN)
        operaciones = _simular_operaciones(symbol, data, cruces)
        todas_las_operaciones.extend(operaciones)

    print()
    print("=" * 100)
    print("DESGLOSE MES A MES (todas las criptos juntas, ordenado por fecha de entrada)")
    print("=" * 100)

    por_mes = defaultdict(list)
    for op in todas_las_operaciones:
        clave_mes = op.entrada_fecha.strftime("%Y-%m")
        por_mes[clave_mes].append(op)

    print(f"{'MES':10} {'N':>4} {'GANADORAS':>10} {'NETO TOTAL':>16} {'NETO PROMEDIO':>16}")
    print("-" * 100)

    neto_acumulado = 0.0
    for mes in sorted(por_mes.keys()):
        ops_mes = por_mes[mes]
        neto_mes = sum(op.neto for op in ops_mes)
        ganaron = sum(1 for op in ops_mes if op.neto > 0)
        neto_acumulado += neto_mes

        print(f"{mes:10} {len(ops_mes):>4} {ganaron:>6}/{len(ops_mes):<3} "
              f"${neto_mes:>+15,.0f} ${neto_mes/len(ops_mes):>+15,.0f}")

    print("-" * 100)
    print(f"Total: {len(todas_las_operaciones)} operaciones | neto acumulado ${neto_acumulado:+,.0f} COP")
    print("=" * 100)


if __name__ == "__main__":
    correr()