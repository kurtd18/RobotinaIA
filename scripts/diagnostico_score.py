"""
Diagnóstico de scoring: muestra el valor real de cada indicador para un
activo y si cada condición del score se cumplió o no, para poder
auditar por qué un activo obtuvo el score que obtuvo.

Uso: python scripts/diagnostico_score.py SYMBOL
"""

import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.indicators.technical_indicators import agregar_todos_los_indicadores


def diagnosticar(symbol):
    data = yf.Ticker(symbol).history(period="5d", interval="5m")

    if data.empty:
        print(f"{symbol}: sin datos")
        return

    data = agregar_todos_los_indicadores(data)
    u = data.iloc[-1]

    print("=" * 60)
    print(f"DIAGNÓSTICO DE SCORE: {symbol}")
    print("=" * 60)

    print(f"Precio (Close)     : {u['Close']:.2f}")
    print()

    print(f"RSI                : {u['RSI']:.2f}  -> {'CUMPLE (+10)' if u['RSI'] > 50 else 'no cumple'} (condición: > 50)")
    print(f"EMA9 vs EMA21      : {u['EMA9']:.2f} vs {u['EMA21']:.2f}  -> {'CUMPLE (+10)' if u['EMA9'] > u['EMA21'] else 'no cumple'}")
    print(f"Close vs VWAP      : {u['Close']:.2f} vs {u['VWAP']:.2f}  -> {'CUMPLE (+20)' if u['Close'] > u['VWAP'] else 'no cumple'}")

    macd, macds = u["MACD_12_26_9"], u["MACDs_12_26_9"]
    if macd is not None and macds is not None:
        print(f"MACD vs señal      : {macd:.4f} vs {macds:.4f}  -> {'CUMPLE (+10)' if macd > macds else 'no cumple'}")
    else:
        print("MACD vs señal      : sin datos suficientes -> no cumple")

    print(f"Volumen vs promedio: {u['Volume']:.0f} vs {u['VOL_AVG']:.0f}  -> {'CUMPLE (+15)' if u['Volume'] > u['VOL_AVG'] else 'no cumple'}")

    atr_pct = (u["ATR"] / u["Close"] * 100) if u["Close"] else None
    if atr_pct is not None:
        print(f"ATR como % precio  : {atr_pct:.4f}%  -> {'CUMPLE (+5)' if atr_pct > 0.3 else 'no cumple'} (condición: > 0.3%)")
    else:
        print("ATR como % precio  : sin datos -> no cumple")

    mom = u["MOM14"]
    if mom is not None:
        print(f"Momento14          : {mom:.4f}  -> {'CUMPLE (+15)' if mom > 0 else 'no cumple'} (condición: > 0)")
    else:
        print("Momento14          : sin datos suficientes -> no cumple")

    bbu = u["BBU_20_2.0_2.0"]
    if bbu is not None:
        print(f"Close vs Bollinger : {u['Close']:.2f} vs {bbu:.2f}  -> {'CUMPLE (+10)' if u['Close'] > bbu else 'no cumple'} (ruptura banda superior)")
    else:
        print("Close vs Bollinger : sin datos suficientes -> no cumple")

    print()
    print("Peso temporal fijo : +5 (siempre)")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/diagnostico_score.py SYMBOL")
        sys.exit(1)

    diagnosticar(sys.argv[1])