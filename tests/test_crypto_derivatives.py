"""
Pruebas del provider (historial de funding rate / open interest) y del
módulo de derivados. Todo mockeado - no dependen de Internet.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.derivatives.crypto_derivatives import (
    calcular_derivados,
    calcular_funding_rate,
    calcular_open_interest,
)
from app.providers.binance_provider import BinanceProvider, BinanceProviderError


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


# ---------- BinanceProvider: historial de funding rate ----------

@patch("app.providers.binance_provider.requests.get")
def test_get_funding_rate_history_ok(mock_get):
    mock_get.return_value = FakeResponse([
        {"symbol": "BTCUSDT", "fundingRate": "0.00010", "fundingTime": 1735689600000},
        {"symbol": "BTCUSDT", "fundingRate": "0.00020", "fundingTime": 1735718400000},
    ])

    provider = BinanceProvider()
    historial = provider.get_funding_rate_history("BTCUSDT", limit=2)

    assert len(historial) == 2
    assert historial[0]["funding_rate"] == pytest.approx(0.0001)
    assert historial[0]["funding_time"] == datetime(2025, 1, 1, tzinfo=timezone.utc)


@patch("app.providers.binance_provider.requests.get")
def test_get_funding_rate_history_vacio_lanza_error(mock_get):
    mock_get.return_value = FakeResponse([])

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_funding_rate_history("BTCUSDT")


# ---------- BinanceProvider: historial de open interest ----------

def test_get_open_interest_history_periodo_invalido():
    provider = BinanceProvider()
    with pytest.raises(ValueError):
        provider.get_open_interest_history("BTCUSDT", period="3h")


@patch("app.providers.binance_provider.requests.get")
def test_get_open_interest_history_ok(mock_get):
    mock_get.return_value = FakeResponse([
        {"symbol": "ETHUSDT", "sumOpenInterest": "1000.0", "timestamp": 1735689600000},
        {"symbol": "ETHUSDT", "sumOpenInterest": "1100.0", "timestamp": 1735693200000},
    ])

    provider = BinanceProvider()
    historial = provider.get_open_interest_history("ETHUSDT", period="1h", limit=2)

    assert len(historial) == 2
    assert historial[-1]["open_interest"] == pytest.approx(1100.0)


@patch("app.providers.binance_provider.requests.get")
def test_get_open_interest_history_vacio_lanza_error(mock_get):
    mock_get.return_value = FakeResponse([])

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_open_interest_history("ETHUSDT")


# ---------- crypto_derivatives: funding rate ----------

def _mock_funding_history(tasas):
    provider = MagicMock()
    provider.get_funding_rate_history.return_value = [
        {"symbol": "BTCUSDT", "funding_rate": tasa, "funding_time": datetime.now(timezone.utc)}
        for tasa in tasas
    ]
    return provider


def test_calcular_funding_rate_tendencia_subiendo():
    provider = _mock_funding_history([0.0001, 0.0001, 0.0005, 0.0006])

    resultado = calcular_funding_rate("BTCUSDT", provider=provider)

    assert resultado["funding_rate_actual"] == pytest.approx(0.0006)
    assert resultado["funding_rate_tendencia"] == "subiendo"
    assert len(resultado["historial"]) == 4


def test_calcular_funding_rate_tendencia_estable():
    provider = _mock_funding_history([0.0001, 0.0001, 0.0001, 0.0001])

    resultado = calcular_funding_rate("BTCUSDT", provider=provider)

    assert resultado["funding_rate_tendencia"] == "estable"


# ---------- crypto_derivatives: open interest ----------

def _mock_oi_history(valores):
    provider = MagicMock()
    provider.get_open_interest_history.return_value = [
        {"symbol": "ETHUSDT", "open_interest": v, "time": datetime.now(timezone.utc)}
        for v in valores
    ]
    return provider


def test_calcular_open_interest_tendencia_bajando():
    provider = _mock_oi_history([1000.0, 1000.0, 800.0, 700.0])

    resultado = calcular_open_interest("ETHUSDT", provider=provider)

    assert resultado["open_interest_actual"] == pytest.approx(700.0)
    assert resultado["open_interest_tendencia"] == "bajando"
    assert resultado["open_interest_variacion_pct"] < 0


def test_calcular_open_interest_pasa_period_y_limit_al_provider():
    provider = _mock_oi_history([1000.0, 1000.0])

    calcular_open_interest("ETHUSDT", provider=provider, period="1h", limit=10)

    provider.get_open_interest_history.assert_called_once_with("ETHUSDT", period="1h", limit=10)


# ---------- crypto_derivatives: combinado ----------

def test_calcular_derivados_combina_funding_y_oi():
    provider = MagicMock()
    provider.get_funding_rate_history.return_value = [
        {"symbol": "BTCUSDT", "funding_rate": 0.0001, "funding_time": datetime.now(timezone.utc)}
    ]
    provider.get_open_interest_history.return_value = [
        {"symbol": "BTCUSDT", "open_interest": 1000.0, "time": datetime.now(timezone.utc)}
    ]

    resultado = calcular_derivados("BTCUSDT", provider=provider)

    assert resultado["symbol"] == "BTCUSDT"
    assert "funding_rate" in resultado
    assert "open_interest" in resultado
