"""
Pruebas de FearGreedProvider y del módulo de sentimiento. Todo mockeado
- no dependen de Internet.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.sentiment.crypto_sentiment import calcular_sentimiento
from app.sentiment.fear_greed_provider import FearGreedProvider, FearGreedProviderError


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


# ---------- FearGreedProvider ----------

@patch("app.sentiment.fear_greed_provider.requests.get")
def test_get_index_history_ok_y_orden_cronologico(mock_get):
    # la API real entrega el más reciente primero
    mock_get.return_value = FakeResponse({
        "data": [
            {"value": "60", "value_classification": "Greed", "timestamp": "1735776000"},
            {"value": "50", "value_classification": "Neutral", "timestamp": "1735689600"},
        ]
    })

    provider = FearGreedProvider()
    historial = provider.get_index_history(limit=2)

    assert len(historial) == 2
    assert historial[0]["valor"] == 50  # el más antiguo queda primero
    assert historial[-1]["valor"] == 60
    assert historial[-1]["clasificacion"] == "Greed"


@patch("app.sentiment.fear_greed_provider.requests.get")
def test_get_index_history_vacio_lanza_error(mock_get):
    mock_get.return_value = FakeResponse({"data": []})

    provider = FearGreedProvider()
    with pytest.raises(FearGreedProviderError):
        provider.get_index_history()


@patch("app.sentiment.fear_greed_provider.requests.get")
def test_get_index_history_http_error_lanza_provider_error(mock_get):
    mock_get.return_value = FakeResponse({"msg": "error"}, status_code=500)

    provider = FearGreedProvider()
    with pytest.raises(FearGreedProviderError):
        provider.get_index_history()


@patch("app.sentiment.fear_greed_provider.time.sleep", return_value=None)
@patch("app.sentiment.fear_greed_provider.requests.get")
def test_timeout_agota_reintentos_y_lanza_provider_error(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.Timeout("timed out")

    provider = FearGreedProvider()
    with pytest.raises(FearGreedProviderError):
        provider.get_index_history()

    assert mock_get.call_count == 3


@patch("app.sentiment.fear_greed_provider.time.sleep", return_value=None)
@patch("app.sentiment.fear_greed_provider.requests.get")
def test_rate_limit_reintenta_y_luego_responde_ok(mock_get, mock_sleep):
    mock_get.side_effect = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "1"}),
        FakeResponse({"data": [{"value": "40", "value_classification": "Fear", "timestamp": "1735689600"}]}),
    ]

    provider = FearGreedProvider()
    historial = provider.get_index_history(limit=1)

    assert historial[0]["valor"] == 40
    mock_sleep.assert_called_once_with(1)


# ---------- crypto_sentiment ----------

def _mock_provider(valores):
    provider = MagicMock()
    provider.get_index_history.return_value = [
        {"valor": v, "clasificacion": "Neutral", "timestamp": None} for v in valores
    ]
    return provider


def test_calcular_sentimiento_tendencia_subiendo():
    provider = _mock_provider([30, 30, 60, 65])

    resultado = calcular_sentimiento(provider=provider)

    assert resultado["valor_actual"] == 65
    assert resultado["tendencia"] == "subiendo"


def test_calcular_sentimiento_tendencia_estable():
    provider = _mock_provider([50, 51, 49, 50])

    resultado = calcular_sentimiento(provider=provider)

    assert resultado["tendencia"] == "estable"


def test_calcular_sentimiento_incluye_clasificacion_y_promedio():
    provider = _mock_provider([20, 40])
    provider.get_index_history.return_value = [
        {"valor": 20, "clasificacion": "Extreme Fear", "timestamp": None},
        {"valor": 40, "clasificacion": "Fear", "timestamp": None},
    ]

    resultado = calcular_sentimiento(provider=provider)

    assert resultado["clasificacion_actual"] == "Fear"
    assert resultado["valor_promedio"] == pytest.approx(30.0)
