"""
Escáner manual de vigilancia (watchlist).

No forma parte del pipeline automático de scoring — es una herramienta
para revisar rápido el estado de un activo antes de agregarlo al
scoring, o para chequear el mercado a mano.

Uso: python scripts/watchlist_scanner.py
"""

import sys
from pathlib import Path

import yfinance as yf

# Permite correr este script directamente (python scripts/watchlist_scanner.py)
# sin depender del directorio desde el que se invoque.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings


def escanear(activos):
    print("=" * 50)
    print("ROBOTINAIA - WATCHLIST SCANNER")
    print("=" * 50)

    for activo in activos:
        try:
            info = yf.Ticker(activo).info

            precio = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("previousClose")
            )

            print(f"""
Activo: {activo}
Precio: {precio}
Variación: {info.get('regularMarketChangePercent')}
Volumen: {info.get('volume')}
            """)

        except Exception as e:
            print(f"ERROR: {activo}")
            print(e)

    print("=" * 50)


if __name__ == "__main__":
    escanear(Settings.todos_los_activos())