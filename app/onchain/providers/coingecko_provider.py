"""
Proveedor de datos de suministro vía la API pública ("keyless") de
CoinGecko - sin API key, para BTC y ETH.

https://docs.coingecko.com/reference/coins-id
"""

import time

import requests
from loguru import logger

BASE_URL = "https://api.coingecko.com/api/v3"

TIMEOUT_SEGUNDOS = 15
MAX_REINTENTOS = 3
CODIGOS_RATE_LIMIT = {429, 418}


class CoinGeckoProviderError(Exception):
    """Error al consultar la API pública de CoinGecko."""


class CoinGeckoProvider:
    """Proveedor de solo lectura sobre la API pública de CoinGecko."""

    def get_supply(self, coin_id: str) -> dict:
        """
        Devuelve el suministro actual de una moneda:
        {"coin_id", "circulating_supply", "total_supply", "market_cap_usd"}

        coin_id: id de CoinGecko (ej. "bitcoin", "ethereum")
        """
        url = f"{BASE_URL}/coins/{coin_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
        }
        datos = self._pedir(url, params, contexto=f"suministro de {coin_id}")

        market_data = datos.get("market_data") if isinstance(datos, dict) else None
        if not market_data:
            logger.warning(f"CoinGecko no devolvió market_data para {coin_id}")
            raise CoinGeckoProviderError(f"Sin datos de suministro para {coin_id}")

        resultado = {
            "coin_id": coin_id,
            "circulating_supply": market_data.get("circulating_supply"),
            "total_supply": market_data.get("total_supply"),
            "market_cap_usd": (market_data.get("market_cap") or {}).get("usd"),
        }
        logger.info(
            f"OK: suministro {coin_id} circulante={resultado['circulating_supply']} "
            f"total={resultado['total_supply']}"
        )
        return resultado

    def _pedir(self, url: str, params: dict, contexto: str):
        ultimo_error = None

        for intento in range(MAX_REINTENTOS):
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT_SEGUNDOS)

                if resp.status_code in CODIGOS_RATE_LIMIT:
                    espera = int(resp.headers.get("Retry-After", 2 ** (intento + 1)))
                    logger.warning(
                        f"Rate limit consultando {contexto} (HTTP {resp.status_code}), "
                        f"esperando {espera}s..."
                    )
                    time.sleep(espera)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.HTTPError as e:
                logger.error(f"Error HTTP consultando {contexto}: {e}")
                raise CoinGeckoProviderError(f"Error HTTP consultando {contexto}") from e
            except requests.exceptions.RequestException as e:
                ultimo_error = e
                espera = 2 ** intento
                logger.warning(
                    f"Falla de red consultando {contexto}, reintentando en {espera}s... "
                    f"(intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})"
                )
                time.sleep(espera)

        logger.error(f"Se agotaron los reintentos consultando {contexto}: {ultimo_error}")
        raise CoinGeckoProviderError(
            f"No se pudo consultar {contexto} tras {MAX_REINTENTOS} intentos"
        ) from ultimo_error
