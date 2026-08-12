"""
Proveedor de TVL (Total Value Locked) vía la API pública de DefiLlama -
sin API key, sin límites documentados para tráfico normal.

https://api-docs.defillama.com/
"""

from datetime import datetime, timezone
import time

import requests
from loguru import logger

BASE_URL = "https://api.llama.fi"

TIMEOUT_SEGUNDOS = 15
MAX_REINTENTOS = 3
CODIGOS_RATE_LIMIT = {429, 418}


class DefiLlamaProviderError(Exception):
    """Error al consultar la API pública de DefiLlama."""


class DefiLlamaProvider:
    """Proveedor de solo lectura sobre la API pública de DefiLlama."""

    def get_chain_tvl_history(self, chain: str) -> list[dict]:
        """
        Devuelve el historial de TVL de una chain (más antiguo primero):
        [{"timestamp": datetime UTC, "tvl_usd": float}, ...]

        chain: nombre de la chain tal como lo usa DefiLlama (ej. "Ethereum",
        "Arbitrum", "Optimism", "Base").
        """
        url = f"{BASE_URL}/v2/historicalChainTvl/{chain}"
        datos = self._pedir(url, contexto=f"TVL histórico de {chain}")

        if not datos:
            logger.warning(f"DefiLlama no devolvió TVL para {chain}")
            raise DefiLlamaProviderError(f"Sin datos de TVL para {chain}")

        resultado = [
            {
                "timestamp": datetime.fromtimestamp(item["date"], tz=timezone.utc),
                "tvl_usd": float(item["tvl"]),
            }
            for item in datos
        ]
        logger.info(f"OK: {len(resultado)} registros de TVL para {chain}")
        return resultado

    def _pedir(self, url: str, contexto: str):
        ultimo_error = None

        for intento in range(MAX_REINTENTOS):
            try:
                resp = requests.get(url, timeout=TIMEOUT_SEGUNDOS)

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
                raise DefiLlamaProviderError(f"Error HTTP consultando {contexto}") from e
            except requests.exceptions.RequestException as e:
                ultimo_error = e
                espera = 2 ** intento
                logger.warning(
                    f"Falla de red consultando {contexto}, reintentando en {espera}s... "
                    f"(intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})"
                )
                time.sleep(espera)

        logger.error(f"Se agotaron los reintentos consultando {contexto}: {ultimo_error}")
        raise DefiLlamaProviderError(
            f"No se pudo consultar {contexto} tras {MAX_REINTENTOS} intentos"
        ) from ultimo_error
