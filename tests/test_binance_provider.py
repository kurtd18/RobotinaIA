"""
Pruebas de BinanceProvider. Todo mockeado - no dependen de Internet.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
import requests

from app.providers.binance_provider import BinanceProvider, BinanceProviderError


def _df_ohlcv(n=5):
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [10.0 + i for i in range(n)],
        },
        index=idx,
    )


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


# ---------- get_ohlcv ----------

def test_get_ohlcv_intervalo_invalido():
    provider = BinanceProvider()
    with pytest.raises(ValueError):
        provider.get_ohlcv("BTCUSDT", "2h")


@patch("app.providers.binance_provider.obtener_klines")
def test_get_ohlcv_devuelve_dataframe(mock_klines):
    mock_klines.return_value = _df_ohlcv(10)

    provider = BinanceProvider()
    df = provider.get_ohlcv("BTCUSDT", "15m", num_velas=5)

    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 5
    mock_klines.assert_called_once()


@patch("app.providers.binance_provider.obtener_klines")
def test_get_ohlcv_respuesta_vacia_lanza_error(mock_klines):
    mock_klines.return_value = None

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_ohlcv("BTCUSDT", "1h")


@patch("app.providers.binance_provider.obtener_klines")
def test_get_ohlcv_dataframe_vacio_lanza_error(mock_klines):
    mock_klines.return_value = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_ohlcv("ETHUSDT", "4h")


@patch("app.providers.binance_provider.obtener_klines")
def test_get_ohlcv_error_de_red_se_propaga_como_binance_error(mock_klines):
    mock_klines.side_effect = requests.exceptions.ConnectionError("no network")

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_ohlcv("BTCUSDT", "1h")


# ---------- get_funding_rate ----------

@patch("app.providers.binance_provider.requests.get")
def test_get_funding_rate_ok(mock_get):
    mock_get.return_value = FakeResponse([
        {"symbol": "BTCUSDT", "fundingRate": "0.00010000", "fundingTime": 1735689600000}
    ])

    provider = BinanceProvider()
    resultado = provider.get_funding_rate("BTCUSDT")

    assert resultado["symbol"] == "BTCUSDT"
    assert resultado["funding_rate"] == pytest.approx(0.0001)
    assert resultado["funding_time"] == datetime(2025, 1, 1, tzinfo=timezone.utc)


@patch("app.providers.binance_provider.requests.get")
def test_get_funding_rate_respuesta_vacia_lanza_error(mock_get):
    mock_get.return_value = FakeResponse([])

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_funding_rate("BTCUSDT")


@patch("app.providers.binance_provider.requests.get")
def test_get_funding_rate_http_error_lanza_binance_error(mock_get):
    mock_get.return_value = FakeResponse({"msg": "Invalid symbol"}, status_code=400)

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_funding_rate("NOEXISTE")


# ---------- get_open_interest ----------

@patch("app.providers.binance_provider.requests.get")
def test_get_open_interest_ok(mock_get):
    mock_get.return_value = FakeResponse(
        {"symbol": "ETHUSDT", "openInterest": "12345.678", "time": 1735689600000}
    )

    provider = BinanceProvider()
    resultado = provider.get_open_interest("ETHUSDT")

    assert resultado["symbol"] == "ETHUSDT"
    assert resultado["open_interest"] == pytest.approx(12345.678)
    assert resultado["time"] == datetime(2025, 1, 1, tzinfo=timezone.utc)


@patch("app.providers.binance_provider.requests.get")
def test_get_open_interest_respuesta_vacia_lanza_error(mock_get):
    mock_get.return_value = FakeResponse({})

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_open_interest("ETHUSDT")


# ---------- rate limit / timeouts ----------

@patch("app.providers.binance_provider.time.sleep", return_value=None)
@patch("app.providers.binance_provider.requests.get")
def test_rate_limit_reintenta_y_luego_responde_ok(mock_get, mock_sleep):
    mock_get.side_effect = [
        FakeResponse({"error": "rate limited"}, status_code=429, headers={"Retry-After": "1"}),
        FakeResponse({"symbol": "BTCUSDT", "openInterest": "500.0", "time": 1735689600000}),
    ]

    provider = BinanceProvider()
    resultado = provider.get_open_interest("BTCUSDT")

    assert resultado["open_interest"] == pytest.approx(500.0)
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("app.providers.binance_provider.time.sleep", return_value=None)
@patch("app.providers.binance_provider.requests.get")
def test_timeout_agota_reintentos_y_lanza_binance_error(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.Timeout("timed out")

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_funding_rate("BTCUSDT")

    assert mock_get.call_count == 3  # MAX_REINTENTOS


# ---------- get_stock (adaptador MarketDataProvider) ----------

@patch("app.providers.binance_provider.obtener_klines")
def test_get_stock_devuelve_ultimo_precio(mock_klines):
    mock_klines.return_value = _df_ohlcv(3)

    provider = BinanceProvider()
    stock = provider.get_stock("BTCUSDT")

    assert stock.symbol == "BTCUSDT"
    assert stock.price == pytest.approx(102.5)  # Close de la última vela de _df_ohlcv(3)


# ---------- get_long_short_ratio ----------

def test_get_long_short_ratio_periodo_invalido():
    provider = BinanceProvider()
    with pytest.raises(ValueError):
        provider.get_long_short_ratio("BTCUSDT", period="3h")


@patch("app.providers.binance_provider.requests.get")
def test_get_long_short_ratio_ok(mock_get):
    mock_get.return_value = FakeResponse([
        {"symbol": "BTCUSDT", "longShortRatio": "1.85", "longAccount": "0.649",
         "shortAccount": "0.351", "timestamp": 1735689600000},
    ])

    provider = BinanceProvider()
    historial = provider.get_long_short_ratio("BTCUSDT")

    assert historial[-1]["long_short_ratio"] == pytest.approx(1.85)
    assert historial[-1]["time"] == datetime(2025, 1, 1, tzinfo=timezone.utc)


@patch("app.providers.binance_provider.requests.get")
def test_get_long_short_ratio_vacio_lanza_error(mock_get):
    mock_get.return_value = FakeResponse([])

    provider = BinanceProvider()
    with pytest.raises(BinanceProviderError):
        provider.get_long_short_ratio("BTCUSDT")


# ---------- get_liquidation_orders ----------

@patch("app.providers.binance_provider.requests.get")
def test_get_liquidation_orders_ok(mock_get):
    mock_get.return_value = FakeResponse([
        {"symbol": "BTCUSDT", "side": "SELL", "price": "64000.0", "origQty": "0.5", "time": 1735689600000},
        {"symbol": "BTCUSDT", "side": "BUY", "price": "64100.0", "origQty": "0.2", "time": 1735689700000},
    ])

    provider = BinanceProvider()
    ordenes = provider.get_liquidation_orders("BTCUSDT")

    assert len(ordenes) == 2
    assert ordenes[0]["side"] == "SELL"
    assert ordenes[0]["quantity"] == pytest.approx(0.5)


@patch("app.providers.binance_provider.requests.get")
def test_get_liquidation_orders_vacio_es_dato_valido_no_error(mock_get):
    mock_get.return_value = FakeResponse([])

    provider = BinanceProvider()
    ordenes = provider.get_liquidation_orders("BTCUSDT")

    assert ordenes == []
