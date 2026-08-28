"""
Proveedor de datos de mercado cripto para RobotinaIA, sobre las APIs
públicas de Binance - sin API key, solo lectura de datos de mercado.
No permite operar (no hay endpoints autenticados ni de trading acá).

Fuentes:
- Velas OHLCV: API pública de Binance Spot (reutiliza
  scripts/binance_data.py, ya probado en los backtests existentes).
- Funding rate y open interest: API pública de Binance Futures (USDT-M),
  que también es de solo lectura y no requiere autenticación.

Implementa MarketDataProvider.get_stock() como adaptador delgado (último
precio de cierre) para mantener el contrato existente. Los métodos
específicos de cripto (OHLCV multi-timeframe, funding rate, open
interest) se exponen aparte porque el dataclass Stock
(symbol/company_name/price) no representa velas ni derivados.
"""

from datetime import datetime, timedelta, timezone
import time

import pandas as pd
import requests
from loguru import logger

from app.models.stock import Stock
from app.providers.market_data_provider import MarketDataProvider
from scripts.binance_data import INTERVALO_A_MS, obtener_klines

BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
FUNDING_RATE_ENDPOINT = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/fundingRate"
OPEN_INTEREST_ENDPOINT = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/openInterest"
OPEN_INTEREST_HIST_ENDPOINT = f"{BINANCE_FUTURES_BASE_URL}/futures/data/openInterestHist"
GLOBAL_LONG_SHORT_RATIO_ENDPOINT = f"{BINANCE_FUTURES_BASE_URL}/futures/data/globalLongShortAccountRatio"
FORCE_ORDERS_ENDPOINT = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/allForceOrders"

PERIODOS_OI_SOPORTADOS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")

TIMEOUT_SEGUNDOS = 15
MAX_REINTENTOS = 3

# Códigos HTTP de rate limit de Binance: 429 (demasiadas solicitudes) y
# 418 (IP bloqueada temporalmente por insistir tras un 429).
CODIGOS_RATE_LIMIT = {429, 418}

INTERVALOS_SOPORTADOS = ("15m", "1h", "4h")


class BinanceProviderError(Exception):
    """Error al consultar la API pública de Binance."""


class BinanceProvider(MarketDataProvider):
    """Proveedor de solo lectura sobre las APIs públicas de Binance."""

    def get_ohlcv(self, symbol: str, interval: str, num_velas: int = 100) -> pd.DataFrame:
        """
        Devuelve un DataFrame OHLCV (columnas Open/High/Low/Close/Volume,
        indexado por fecha UTC) con las últimas `num_velas` velas.

        symbol: ej. "BTCUSDT"
        interval: "15m", "1h" o "4h"
        """
        if interval not in INTERVALOS_SOPORTADOS:
            raise ValueError(
                f"Intervalo '{interval}' no soportado. Usa uno de: {INTERVALOS_SOPORTADOS}"
            )

        paso_ms = INTERVALO_A_MS[interval]
        fecha_fin = datetime.now(timezone.utc)
        # pedimos un margen extra de velas por si Binance no tiene aún la
        # vela más reciente cerrada, o hay algún hueco puntual
        fecha_inicio = fecha_fin - timedelta(milliseconds=paso_ms * (num_velas + 5))

        logger.info(f"Solicitando OHLCV {symbol} {interval} a Binance...")

        try:
            df = obtener_klines(symbol, interval, fecha_inicio, fecha_fin)
        except requests.exceptions.RequestException as e:
            logger.error(f"Fallo de red pidiendo OHLCV {symbol} {interval}: {e}")
            raise BinanceProviderError(f"No se pudo obtener OHLCV para {symbol} {interval}") from e

        if df is None or df.empty:
            logger.warning(f"Binance devolvió una respuesta vacía para {symbol} {interval}")
            raise BinanceProviderError(f"Sin datos OHLCV para {symbol} {interval}")

        logger.info(f"OK: {len(df)} velas recibidas para {symbol} {interval}")
        return df.tail(num_velas)

    def get_funding_rate(self, symbol: str) -> dict:
        """
        Devuelve el funding rate más reciente para `symbol` (ej. "BTCUSDT"):
        {"symbol": ..., "funding_rate": float, "funding_time": datetime UTC}
        """
        params = {"symbol": symbol, "limit": 1}
        datos = self._pedir_futures(FUNDING_RATE_ENDPOINT, params, contexto=f"funding rate {symbol}")

        if not datos:
            logger.warning(f"Binance no devolvió funding rate para {symbol}")
            raise BinanceProviderError(f"Sin funding rate para {symbol}")

        ultimo = datos[-1]
        resultado = {
            "symbol": ultimo["symbol"],
            "funding_rate": float(ultimo["fundingRate"]),
            "funding_time": datetime.fromtimestamp(ultimo["fundingTime"] / 1000, tz=timezone.utc),
        }
        logger.info(f"OK: funding rate {symbol} = {resultado['funding_rate']:.6f}")
        return resultado

    def get_funding_rate_history(self, symbol: str, limit: int = 30,
                                  start_time: "datetime" = None, end_time: "datetime" = None) -> list[dict]:
        """
        Devuelve el historial de funding rate para `symbol` (más antiguo
        primero), como lista de {"symbol", "funding_rate", "funding_time"}.

        start_time/end_time (opcionales, datetime): a diferencia de open
        interest y long/short ratio, el funding rate sí tiene historial
        largo en Binance - permite pedir un rango de fechas específico
        (ej. para backtesting) en vez de solo "los últimos N registros".
        """
        params = {"symbol": symbol, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)
        datos = self._pedir_futures(
            FUNDING_RATE_ENDPOINT, params, contexto=f"historial de funding rate {symbol}"
        )

        if not datos:
            logger.warning(f"Binance no devolvió historial de funding rate para {symbol}")
            raise BinanceProviderError(f"Sin historial de funding rate para {symbol}")

        resultado = [
            {
                "symbol": item["symbol"],
                "funding_rate": float(item["fundingRate"]),
                "funding_time": datetime.fromtimestamp(item["fundingTime"] / 1000, tz=timezone.utc),
            }
            for item in datos
        ]
        logger.info(f"OK: {len(resultado)} registros de funding rate histórico para {symbol}")
        return resultado

    def get_open_interest(self, symbol: str) -> dict:
        """
        Devuelve el open interest actual para `symbol` (ej. "BTCUSDT"):
        {"symbol": ..., "open_interest": float, "time": datetime UTC}
        """
        params = {"symbol": symbol}
        datos = self._pedir_futures(OPEN_INTEREST_ENDPOINT, params, contexto=f"open interest {symbol}")

        if not datos or "openInterest" not in datos:
            logger.warning(f"Binance no devolvió open interest para {symbol}")
            raise BinanceProviderError(f"Sin open interest para {symbol}")

        resultado = {
            "symbol": datos["symbol"],
            "open_interest": float(datos["openInterest"]),
            "time": datetime.fromtimestamp(datos["time"] / 1000, tz=timezone.utc),
        }
        logger.info(f"OK: open interest {symbol} = {resultado['open_interest']}")
        return resultado

    def get_open_interest_history(self, symbol: str, period: str = "4h", limit: int = 30) -> list[dict]:
        """
        Devuelve el historial de open interest para `symbol` (más antiguo
        primero), como lista de {"symbol", "open_interest", "time"}.

        period: granularidad de los snapshots, ej. "4h" (ver
        PERIODOS_OI_SOPORTADOS). Binance solo guarda ~30 días de historial.
        """
        if period not in PERIODOS_OI_SOPORTADOS:
            raise ValueError(
                f"Periodo '{period}' no soportado. Usa uno de: {PERIODOS_OI_SOPORTADOS}"
            )

        params = {"symbol": symbol, "period": period, "limit": limit}
        datos = self._pedir_futures(
            OPEN_INTEREST_HIST_ENDPOINT, params, contexto=f"historial de open interest {symbol}"
        )

        if not datos:
            logger.warning(f"Binance no devolvió historial de open interest para {symbol}")
            raise BinanceProviderError(f"Sin historial de open interest para {symbol}")

        resultado = [
            {
                "symbol": item["symbol"],
                "open_interest": float(item["sumOpenInterest"]),
                "time": datetime.fromtimestamp(item["timestamp"] / 1000, tz=timezone.utc),
            }
            for item in datos
        ]
        logger.info(f"OK: {len(resultado)} registros de open interest histórico para {symbol}")
        return resultado

    def get_long_short_ratio(self, symbol: str, period: str = "4h", limit: int = 30) -> list[dict]:
        """
        Devuelve el historial del ratio global de cuentas long/short
        (más antiguo primero): [{"symbol", "long_short_ratio",
        "long_account_pct", "short_account_pct", "time"}, ...]

        period: granularidad, ver PERIODOS_OI_SOPORTADOS (mismo set que open interest).
        """
        if period not in PERIODOS_OI_SOPORTADOS:
            raise ValueError(
                f"Periodo '{period}' no soportado. Usa uno de: {PERIODOS_OI_SOPORTADOS}"
            )

        params = {"symbol": symbol, "period": period, "limit": limit}
        datos = self._pedir_futures(
            GLOBAL_LONG_SHORT_RATIO_ENDPOINT, params, contexto=f"long/short ratio {symbol}"
        )

        if not datos:
            logger.warning(f"Binance no devolvió long/short ratio para {symbol}")
            raise BinanceProviderError(f"Sin long/short ratio para {symbol}")

        resultado = [
            {
                "symbol": item["symbol"],
                "long_short_ratio": float(item["longShortRatio"]),
                "long_account_pct": float(item["longAccount"]),
                "short_account_pct": float(item["shortAccount"]),
                "time": datetime.fromtimestamp(item["timestamp"] / 1000, tz=timezone.utc),
            }
            for item in datos
        ]
        logger.info(f"OK: {len(resultado)} registros de long/short ratio para {symbol}")
        return resultado

    def get_liquidation_orders(self, symbol: str, limit: int = 100) -> list[dict]:
        """
        Devuelve las órdenes de liquidación forzada más recientes:
        [{"symbol", "side", "price", "quantity", "time"}, ...]

        side: "BUY" (se liquidó una posición corta) o "SELL" (se liquidó
        una posición larga), según el lado de la orden de liquidación.

        NOTA (verificado en ejecución real): la documentación de Binance
        describe este endpoint como público, pero en la práctica responde
        HTTP 404 - Binance lo restringió en algún momento y ya no está
        disponible sin autenticación. Se deja implementado (por si
        Binance lo reactiva) pero quien lo use debe esperar que casi
        siempre falle con BinanceProviderError.
        """
        params = {"symbol": symbol, "limit": limit}
        datos = self._pedir_futures(
            FORCE_ORDERS_ENDPOINT, params, contexto=f"liquidaciones {symbol}"
        )

        # a diferencia de los demás endpoints, una lista vacía acá es un
        # dato real y válido (no hubo liquidaciones recientes), no un
        # fallo - no se trata como error
        if not datos:
            logger.info(f"Sin liquidaciones recientes para {symbol} (lista vacía, dato válido)")
            return []

        resultado = [
            {
                "symbol": item["symbol"],
                "side": item["side"],
                "price": float(item["price"]),
                "quantity": float(item["origQty"]),
                "time": datetime.fromtimestamp(item["time"] / 1000, tz=timezone.utc),
            }
            for item in datos
        ]
        logger.info(f"OK: {len(resultado)} liquidaciones recientes para {symbol}")
        return resultado

    def get_stock(self, symbol: str) -> Stock:
        """
        Adaptador delgado para cumplir el contrato MarketDataProvider:
        retorna el último precio de cierre (vela de 15m) como Stock.
        """
        df = self.get_ohlcv(symbol, "15m", num_velas=1)
        ultimo_precio = float(df["Close"].iloc[-1])
        return Stock(symbol=symbol, company_name=symbol, price=ultimo_precio)

    def _pedir_futures(self, url: str, params: dict, contexto: str):
        """
        GET contra la API pública de Binance Futures, con reintentos con
        espera creciente ante timeouts/errores de red, y espera extra
        ante rate limiting (429/418) respetando Retry-After si viene.
        """
        ultimo_error = None

        for intento in range(MAX_REINTENTOS):
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT_SEGUNDOS)

                if resp.status_code in CODIGOS_RATE_LIMIT:
                    espera = int(resp.headers.get("Retry-After", 2 ** (intento + 1)))
                    logger.warning(
                        f"Rate limit de Binance consultando {contexto} "
                        f"(HTTP {resp.status_code}), esperando {espera}s..."
                    )
                    time.sleep(espera)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.HTTPError as e:
                logger.error(f"Error HTTP consultando {contexto}: {e}")
                raise BinanceProviderError(f"Error HTTP consultando {contexto}") from e
            except requests.exceptions.RequestException as e:
                ultimo_error = e
                espera = 2 ** intento
                logger.warning(
                    f"Falla de red consultando {contexto}, reintentando en {espera}s... "
                    f"(intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})"
                )
                time.sleep(espera)

        logger.error(f"Se agotaron los reintentos consultando {contexto}: {ultimo_error}")
        raise BinanceProviderError(f"No se pudo consultar {contexto} tras {MAX_REINTENTOS} intentos") from ultimo_error
