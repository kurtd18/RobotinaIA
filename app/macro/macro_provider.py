"""
Proveedor de indicadores macro vía Yahoo Finance (yfinance) - misma
fuente que ya usa el resto del proyecto para acciones, sin API key.

Tickers cubiertos:
- DX-Y.NYB: índice dólar (DXY)
- ^TNX: rendimiento del Tesoro de EE.UU. a 10 años
- ^GSPC: S&P 500
- GC=F: futuro de oro
"""

import pandas as pd
import yfinance as yf
from loguru import logger

TICKERS_MACRO = {
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "SP500": "^GSPC",
    "GOLD": "GC=F",
}


class MacroProviderError(Exception):
    """Error al consultar datos macro vía yfinance."""


class MacroProvider:
    """Proveedor de solo lectura sobre Yahoo Finance para indicadores macro."""

    def get_history(self, ticker: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        """
        Devuelve un DataFrame con el histórico de cierre de `ticker`
        (columnas Open/High/Low/Close/Volume, como el resto del proyecto).
        """
        logger.info(f"Solicitando histórico macro {ticker} ({period}, {interval})...")

        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval)
        except Exception as e:
            logger.error(f"Fallo consultando yfinance para {ticker}: {e}")
            raise MacroProviderError(f"No se pudo obtener histórico de {ticker}") from e

        if df is None or df.empty:
            logger.warning(f"yfinance devolvió una respuesta vacía para {ticker}")
            raise MacroProviderError(f"Sin datos históricos para {ticker}")

        logger.info(f"OK: {len(df)} registros recibidos para {ticker}")
        return df
