"""
Proveedor del Fear & Greed Index (alternative.me) - sin API key, solo
lectura de un índice público de sentimiento del mercado cripto en
general (0-100, no es específico de BTC ni de ETH).

https://alternative.me/crypto/fear-and-greed-index/
"""

from datetime import datetime, timezone
import time

import requests
from loguru import logger

FEAR_GREED_ENDPOINT = "https://api.alternative.me/fng/"

TIMEOUT_SEGUNDOS = 15
MAX_REINTENTOS = 3
CODIGOS_RATE_LIMIT = {429, 418}


class FearGreedProviderError(Exception):
    """Error al consultar el Fear & Greed Index."""


class FearGreedProvider:
    """Proveedor de solo lectura sobre la API pública de alternative.me."""

    def get_index_history(self, limit: int = 30) -> list[dict]:
        """
        Devuelve el historial del índice (más antiguo primero):
        [{"valor": int, "clasificacion": str, "timestamp": datetime UTC}, ...]
        """
        params = {"limit": limit, "format": "json"}
        datos = self._pedir(FEAR_GREED_ENDPOINT, params, contexto="Fear & Greed Index")

        registros = datos.get("data") if isinstance(datos, dict) else None
        if not registros:
            logger.warning("alternative.me no devolvió datos de Fear & Greed Index")
            raise FearGreedProviderError("Sin datos de Fear & Greed Index")

        resultado = [
            {
                "valor": int(item["value"]),
                "clasificacion": item["value_classification"],
                "timestamp": datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc),
            }
            for item in registros
        ]
        # la API entrega el más reciente primero; lo invertimos para
        # quedar en orden cronológico ascendente, igual que el resto de
        # historiales del proyecto (funding rate, open interest)
        resultado.reverse()

        logger.info(f"OK: {len(resultado)} registros de Fear & Greed Index")
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
                raise FearGreedProviderError(f"Error HTTP consultando {contexto}") from e
            except requests.exceptions.RequestException as e:
                ultimo_error = e
                espera = 2 ** intento
                logger.warning(
                    f"Falla de red consultando {contexto}, reintentando en {espera}s... "
                    f"(intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})"
                )
                time.sleep(espera)

        logger.error(f"Se agotaron los reintentos consultando {contexto}: {ultimo_error}")
        raise FearGreedProviderError(
            f"No se pudo consultar {contexto} tras {MAX_REINTENTOS} intentos"
        ) from ultimo_error
