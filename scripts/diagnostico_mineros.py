"""
Imprime las velas diarias crudas de MINEROS.CL alrededor de una fecha
específica, directo de Yahoo Finance, sin ningún procesamiento - para
comparar contra lo que se ve en un gráfico real (TradingView/BVC) y
detectar si hay una discrepancia real en los datos.

Uso:
    python scripts/diagnostico_mineros.py
"""

import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

data = yf.Ticker("MINEROS.CL").history(start="2026-06-15", end="2026-07-20", interval="1d")

print("Velas crudas de MINEROS.CL, 15 junio a 20 julio 2026:")
print(f"{'FECHA':12} {'OPEN':>10} {'HIGH':>10} {'LOW':>10} {'CLOSE':>10} {'VOLUME':>10}")
print("-" * 70)
for fecha, fila in data.iterrows():
    print(f"{fecha.strftime('%Y-%m-%d'):12} {fila['Open']:>10,.2f} {fila['High']:>10,.2f} "
          f"{fila['Low']:>10,.2f} {fila['Close']:>10,.2f} {fila['Volume']:>10,.0f}")

print()
print(f"Timezone del índice: {data.index.tz}")