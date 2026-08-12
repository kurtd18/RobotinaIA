"""
Proveedor de datos on-chain de Bitcoin vía la Charts API de
Blockchain.com - pública, sin API key.

https://www.blockchain.com/explorer/api/charts_api
"""

from datetime import datetime, timezone
import time

import requests
from loguru import logger

BASE_URL = "https://api.blockchain.info/charts"

TIMEOUT_SEGUNDOS = 15
MAX_REINTENTOS = 3
CODIGOS_RATE_LIMIT = {429, 418}

# Nombres de gráficas verificados contra la documentación pública de
# Blockchain.com (www.blockchain.com/explorer/charts/...). No se
# inventaron nombres de endpoints.
GRAFICAS = {
    "direcciones_activas": "n-unique-addresses",
    "transacciones": "n-transactions",
    "hash_rate": "hash-rate",
    "dificultad": "difficulty",
    "fees_usd": "transaction-fees-usd",
    "suministro": "total-bitcoins",
    "market_cap": "market-cap",
    "volumen_transacciones_usd": "estimated-transaction-volume-usd",
}


class BlockchainInfoProviderError(Exception):
    """Error al consultar la Charts API de Blockchain.com."""


class BlockchainInfoProvider:
    """Proveedor de solo lectura sobre la Charts API pública de Blockchain.com (BTC)."""

    def get_chart(self, chart_key: str, timespan: str = "30days") -> list[dict]:
        """
        Devuelve el historial de una gráfica (más antiguo primero):
        [{"timestamp": datetime UTC, "valor": float}, ...]

        chart_key: una de las claves de GRAFICAS (ej. "direcciones_activas")
        timespan: ventana de tiempo aceptada por la API (ej. "30days", "1year")
        """
        if chart_key not in GRAFICAS:
            raise ValueError(f"Gráfica '{chart_key}' no soportada. Usa una de: {list(GRAFICAS)}")

        url = f"{BASE_URL}/{GRAFICAS[chart_key]}"
        params = {"timespan": timespan, "format": "json", "sampled": "true"}

        datos = self._pedir(url, params, contexto=f"gráfica BTC {chart_key}")

        valores = datos.get("values") if isinstance(datos, dict) else None
        if not valores:
            logger.warning(f"Blockchain.com no devolvió valores para {chart_key}")
            raise BlockchainInfoProviderError(f"Sin datos para la gráfica {chart_key}")

        resultado = [
            {
                "timestamp": datetime.fromtimestamp(item["x"], tz=timezone.utc),
                "valor": float(item["y"]),
            }
            for item in valores
        ]
        logger.info(f"OK: {len(resultado)} registros para {chart_key} ({GRAFICAS[chart_key]})")
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
                raise BlockchainInfoProviderError(f"Error HTTP consultando {contexto}") from e
            except requests.exceptions.RequestException as e:
                ultimo_error = e
                espera = 2 ** intento
                logger.warning(
                    f"Falla de red consultando {contexto}, reintentando en {espera}s... "
                    f"(intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})"
                )
                time.sleep(espera)

        logger.error(f"Se agotaron los reintentos consultando {contexto}: {ultimo_error}")
        raise BlockchainInfoProviderError(
            f"No se pudo consultar {contexto} tras {MAX_REINTENTOS} intentos"
        ) from ultimo_error
