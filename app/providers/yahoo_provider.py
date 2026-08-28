"""
Proveedor de datos de mercado para acciones (BVC e internacional) de
RobotinaIA, sobre yfinance - sin API key, solo lectura.

Sigue el mismo patrón que BinanceProvider (MAX_REINTENTOS, backoff
exponencial), como implementación hermana, no como subclase - no
comparten código, solo la forma del reintento.

Diferencia deliberada con BinanceProvider: yfinance no expone códigos
HTTP estables a través de su API (a diferencia de requests contra la
API pública de Binance), así que acá no se puede distinguir un rate
limit de un timeout de red - se captura Exception de forma amplia y se
reintenta igual, documentado acá en vez de fingir una granularidad que
la librería no ofrece.
"""

import time

import pandas as pd
import yfinance as yf
from loguru import logger

from app.models.stock import Stock
from app.providers.market_data_provider import MarketDataProvider

MAX_REINTENTOS = 3


class YahooProviderError(Exception):
    """Error al consultar datos de mercado vía yfinance."""


class YahooProvider(MarketDataProvider):
    """Proveedor de solo lectura sobre yfinance, con reintentos."""

    def get_stock(self, symbol: str) -> Stock:
        """
        Retorna el último precio de cierre (vela de 5 minutos) como
        Stock, cumpliendo el contrato MarketDataProvider. Mismo shape de
        llamada que ya se usaba ad hoc en portfolio_alerts.py.
        """
        df = self._historial_con_reintentos(
            symbol, period="1d", interval="5m", contexto=f"precio actual {symbol}"
        )
        ultimo_precio = float(df["Close"].iloc[-1])
        return Stock(symbol=symbol, company_name=symbol, price=ultimo_precio)

    def get_daily_history(self, symbol: str, period: str) -> pd.DataFrame:
        """
        Historial diario (interval="1d") para `symbol` en la ventana
        `period` (ej. "2y"), con el mismo reintento/backoff que
        get_stock. Usado por rsi2_connors.py para el cálculo de
        SMA200/RSI(2).
        """
        return self._historial_con_reintentos(
            symbol, period=period, interval="1d", contexto=f"historial diario {symbol}"
        )

    def get_hourly_history(self, symbol: str, period: str = "30d") -> pd.DataFrame:
        """
        Historial en velas de 1h (interval="1h") para `symbol` en la
        ventana `period` (ej. "30d" da ~700 velas, margen de sobra para
        una SMA200). yfinance limita datos intradía a los últimos 730
        días, así que `period` no puede pedir más que eso.

        Usado como respaldo de BinanceProvider.get_ohlcv() para runners
        de CI alojados en EE.UU., donde la API spot de Binance responde
        HTTP 451 (bloqueo geográfico) - Yahoo Finance no tiene esa
        restricción.
        """
        return self._historial_con_reintentos(
            symbol, period=period, interval="1h", contexto=f"historial horario {symbol}"
        )

    def _historial_con_reintentos(
        self, symbol: str, period: str, interval: str, contexto: str
    ) -> pd.DataFrame:
        """
        yf.Ticker(symbol).history(...) con reintentos y espera creciente
        (2 ** intento) ante cualquier excepción. Un DataFrame vacío se
        trata como error de inmediato, sin reintentar - misma convención
        de "respuesta vacía es error" que BinanceProvider.get_ohlcv, que
        tampoco reintenta sobre una respuesta vacía.
        """
        ultimo_error = None

        for intento in range(MAX_REINTENTOS):
            try:
                df = yf.Ticker(symbol).history(period=period, interval=interval)
            except Exception as e:  # yfinance no expone códigos HTTP estables
                ultimo_error = e
                espera = 2**intento
                logger.warning(
                    f"Falla consultando {contexto} vía yfinance, reintentando en "
                    f"{espera}s... (intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})"
                )
                time.sleep(espera)
                continue

            if df is None or df.empty:
                logger.warning(f"yfinance devolvió una respuesta vacía para {contexto}")
                raise YahooProviderError(f"Respuesta vacía para {contexto}")

            logger.info(f"OK: datos recibidos para {contexto}")
            return df

        logger.error(f"Se agotaron los reintentos consultando {contexto}: {ultimo_error}")
        raise YahooProviderError(
            f"No se pudo obtener {contexto} tras {MAX_REINTENTOS} intentos"
        ) from ultimo_error
