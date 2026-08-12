"""
Pruebas de los providers on-chain (Blockchain.com, DefiLlama, CoinGecko).
Todo mockeado - no dependen de Internet.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests

from app.onchain.providers.blockchain_info_provider import (
    BlockchainInfoProvider,
    BlockchainInfoProviderError,
)
from app.onchain.providers.coingecko_provider import CoinGeckoProvider, CoinGeckoProviderError
from app.onchain.providers.defillama_provider import DefiLlamaProvider, DefiLlamaProviderError


class FakeResponse:
    def __init__(self, json_data, status_code=200, headers=None):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


# ---------- BlockchainInfoProvider ----------

def test_get_chart_clave_invalida():
    provider = BlockchainInfoProvider()
    with pytest.raises(ValueError):
        provider.get_chart("clave-inexistente")


@patch("app.onchain.providers.blockchain_info_provider.requests.get")
def test_get_chart_ok(mock_get):
    mock_get.return_value = FakeResponse({
        "status": "ok",
        "values": [
            {"x": 1735689600, "y": 500000},
            {"x": 1735776000, "y": 510000},
        ],
    })

    provider = BlockchainInfoProvider()
    historial = provider.get_chart("direcciones_activas")

    assert len(historial) == 2
    assert historial[0]["valor"] == 500000
    assert historial[0]["timestamp"] == datetime(2025, 1, 1, tzinfo=timezone.utc)


@patch("app.onchain.providers.blockchain_info_provider.requests.get")
def test_get_chart_vacio_lanza_error(mock_get):
    mock_get.return_value = FakeResponse({"status": "ok", "values": []})

    provider = BlockchainInfoProvider()
    with pytest.raises(BlockchainInfoProviderError):
        provider.get_chart("hash_rate")


@patch("app.onchain.providers.blockchain_info_provider.time.sleep", return_value=None)
@patch("app.onchain.providers.blockchain_info_provider.requests.get")
def test_get_chart_timeout_agota_reintentos(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.Timeout("timed out")

    provider = BlockchainInfoProvider()
    with pytest.raises(BlockchainInfoProviderError):
        provider.get_chart("dificultad")

    assert mock_get.call_count == 3


# ---------- DefiLlamaProvider ----------

@patch("app.onchain.providers.defillama_provider.requests.get")
def test_get_chain_tvl_history_ok(mock_get):
    mock_get.return_value = FakeResponse([
        {"date": 1735689600, "tvl": 50_000_000_000.0},
        {"date": 1735776000, "tvl": 51_000_000_000.0},
    ])

    provider = DefiLlamaProvider()
    historial = provider.get_chain_tvl_history("Ethereum")

    assert len(historial) == 2
    assert historial[-1]["tvl_usd"] == pytest.approx(51_000_000_000.0)


@patch("app.onchain.providers.defillama_provider.requests.get")
def test_get_chain_tvl_history_vacio_lanza_error(mock_get):
    mock_get.return_value = FakeResponse([])

    provider = DefiLlamaProvider()
    with pytest.raises(DefiLlamaProviderError):
        provider.get_chain_tvl_history("Arbitrum")


@patch("app.onchain.providers.defillama_provider.requests.get")
def test_get_chain_tvl_history_http_error(mock_get):
    mock_get.return_value = FakeResponse({}, status_code=404)

    provider = DefiLlamaProvider()
    with pytest.raises(DefiLlamaProviderError):
        provider.get_chain_tvl_history("NoExiste")


# ---------- CoinGeckoProvider ----------

@patch("app.onchain.providers.coingecko_provider.requests.get")
def test_get_supply_ok(mock_get):
    mock_get.return_value = FakeResponse({
        "market_data": {
            "circulating_supply": 19_800_000,
            "total_supply": 21_000_000,
            "market_cap": {"usd": 1_200_000_000_000},
        }
    })

    provider = CoinGeckoProvider()
    datos = provider.get_supply("bitcoin")

    assert datos["circulating_supply"] == 19_800_000
    assert datos["market_cap_usd"] == 1_200_000_000_000


@patch("app.onchain.providers.coingecko_provider.requests.get")
def test_get_supply_sin_market_data_lanza_error(mock_get):
    mock_get.return_value = FakeResponse({})

    provider = CoinGeckoProvider()
    with pytest.raises(CoinGeckoProviderError):
        provider.get_supply("ethereum")


@patch("app.onchain.providers.coingecko_provider.time.sleep", return_value=None)
@patch("app.onchain.providers.coingecko_provider.requests.get")
def test_get_supply_rate_limit_reintenta_y_responde_ok(mock_get, mock_sleep):
    mock_get.side_effect = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "1"}),
        FakeResponse({"market_data": {
            "circulating_supply": 120_000_000, "total_supply": 120_000_000,
            "market_cap": {"usd": 400_000_000_000},
        }}),
    ]

    provider = CoinGeckoProvider()
    datos = provider.get_supply("ethereum")

    assert datos["circulating_supply"] == 120_000_000
    mock_sleep.assert_called_once_with(1)
