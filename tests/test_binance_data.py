"""
Pruebas de scripts/binance_data.py, en particular el manejo de rate
limit (429/418) de _pedir_con_reintentos - bug real encontrado en
producción (Railway): un 429 se relanzaba de inmediato sin reintentar,
dejando activos sin datos técnicos silenciosamente. Todo mockeado, no
depende de Internet.
"""

from unittest.mock import patch

import pytest
import requests

from scripts.binance_data import MAX_REINTENTOS, _pedir_con_reintentos


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


@patch("scripts.binance_data.time.sleep", return_value=None)
@patch("scripts.binance_data.requests.get")
def test_rate_limit_429_reintenta_y_responde_ok(mock_get, mock_sleep):
    mock_get.side_effect = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "1"}),
        FakeResponse([["dato"]]),
    ]

    resultado = _pedir_con_reintentos({"symbol": "SOLUSDT"})

    assert resultado == [["dato"]]
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("scripts.binance_data.time.sleep", return_value=None)
@patch("scripts.binance_data.requests.get")
def test_rate_limit_418_tambien_reintenta(mock_get, mock_sleep):
    mock_get.side_effect = [
        FakeResponse({}, status_code=418),
        FakeResponse([["dato"]]),
    ]

    resultado = _pedir_con_reintentos({"symbol": "SOLUSDT"})

    assert resultado == [["dato"]]
    assert mock_get.call_count == 2


@patch("scripts.binance_data.requests.get")
def test_error_4xx_generico_no_reintenta(mock_get):
    mock_get.return_value = FakeResponse({"msg": "invalid symbol"}, status_code=400)

    with pytest.raises(requests.exceptions.HTTPError):
        _pedir_con_reintentos({"symbol": "NOEXISTE"})

    assert mock_get.call_count == 1  # no reintenta un error de cliente genuino


@patch("scripts.binance_data.time.sleep", return_value=None)
@patch("scripts.binance_data.requests.get")
def test_rate_limit_persistente_agota_reintentos(mock_get, mock_sleep):
    mock_get.return_value = FakeResponse({}, status_code=429)

    with pytest.raises(Exception):
        _pedir_con_reintentos({"symbol": "SOLUSDT"})

    assert mock_get.call_count == MAX_REINTENTOS
