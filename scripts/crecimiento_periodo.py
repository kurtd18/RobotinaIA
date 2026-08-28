"""
Muestra el crecimiento/decrecimiento simple (compra y mantén) de uno o
más activos entre el primer y el último día del período - sin ninguna
estrategia de por medio, solo "¿cuánto valía al inicio vs. al final?".

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/crecimiento_periodo.py
    python scripts/crecimiento_periodo.py --activos TERPEL.CL,NUTRESA.CL
"""

import argparse
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def correr(activos, fecha_inicio):
    print(f"{'ACTIVO':15} {'FECHA INICIO':14} {'PRECIO INICIO':>15} "
          f"{'FECHA FIN':14} {'PRECIO FIN':>15} {'VARIACIÓN':>12}")
    print("-" * 95)

    for symbol in activos:
        data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
        if data.empty:
            print(f"{symbol:15} sin datos")
            continue

        primer_precio = float(data["Close"].iloc[0])
        primer_fecha = data.index[0]
        ultimo_precio = float(data["Close"].iloc[-1])
        ultima_fecha = data.index[-1]

        variacion_pct = ((ultimo_precio - primer_precio) / primer_precio) * 100

        print(f"{symbol:15} {primer_fecha.strftime('%Y-%m-%d'):14} ${primer_precio:>14,.2f} "
              f"{ultima_fecha.strftime('%Y-%m-%d'):14} ${ultimo_precio:>14,.2f} {variacion_pct:>+11.2f}%")

    print()
    print("=" * 100)
    print("DESGLOSE SEMANA A SEMANA")
    print("=" * 100)

    for symbol in activos:
        data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
        if data.empty:
            continue

        print()
        print(f"{symbol}")
        print("-" * 90)
        print(f"{'SEMANA':22} {'PRECIO INICIO':>15} {'PRECIO FIN':>15} {'VAR. SEMANA':>14} {'VAR. ACUMULADA':>16}")
        print("-" * 90)

        data = data.copy()
        data.index = data.index.tz_localize(None)  # evita el aviso de zona horaria al agrupar por semana
        data["periodo"] = data.index.to_period("W")

        precio_base = float(data["Close"].iloc[0])

        for periodo, grupo in data.groupby("periodo"):
            precio_inicio_semana = float(grupo["Close"].iloc[0])
            precio_fin_semana = float(grupo["Close"].iloc[-1])
            var_semana_pct = ((precio_fin_semana - precio_inicio_semana) / precio_inicio_semana) * 100
            var_acumulada_pct = ((precio_fin_semana - precio_base) / precio_base) * 100

            print(f"{str(periodo):22} ${precio_inicio_semana:>14,.2f} ${precio_fin_semana:>14,.2f} "
                  f"{var_semana_pct:>+13.2f}% {var_acumulada_pct:>+15.2f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activos", type=str, default="TERPEL.CL,NUTRESA.CL")
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    args = parser.parse_args()

    activos = args.activos.split(",")

    correr(activos, args.inicio)