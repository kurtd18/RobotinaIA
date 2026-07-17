"""
Proveedor de datos utilizando Yahoo Finance.
"""

import yfinance as yf

from app.models.stock import Stock


class YahooProvider:

    def get_stock(self, symbol: str) -> Stock:
        """
        Obtiene información básica de una acción desde Yahoo Finance.
        """

        ticker = yf.Ticker(symbol)

        info = ticker.info

        company = info.get("longName") or symbol

        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or 0.0
        )

        return Stock(
            symbol=symbol,
            company_name=company,
            price=float(price),
        )