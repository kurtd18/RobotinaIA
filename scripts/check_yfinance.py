"""
Chequeo manual de conectividad con Yahoo Finance.

Uso: python scripts/check_yfinance.py [SYMBOL]
"""

import sys

import yfinance as yf


def check_yfinance(symbol="MINEROS.CL"):
    print(f"Consultando {symbol}...")

    info = yf.Ticker(symbol).info

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        print(f"ERROR: no se obtuvo información válida para {symbol}")
        return

    print(f"OK: {symbol} respondió correctamente")
    print(f"Nombre: {info.get('longName', info.get('shortName', 'N/D'))}")


if __name__ == "__main__":
    simbolo = sys.argv[1] if len(sys.argv) > 1 else "MINEROS.CL"
    check_yfinance(simbolo)