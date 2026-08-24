"""Tests de app/strategies/rsi2_connors.py: cableado a YahooProvider."""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.providers.yahoo_provider import YahooProviderError
from app.strategies import rsi2_connors


def _fixture_historial(n=210, precio_base=100.0):
    """Historial diario sintético, con forma idéntica a lo que devolvía
    yf.Ticker(symbol).history(period=..., interval='1d') antes de este
    cambio: columnas Open/High/Low/Close/Volume, indexado por fecha."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="America/New_York")
    precios = precio_base + np.cumsum(np.random.default_rng(42).normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "Open": precios,
            "High": precios + 1,
            "Low": precios - 1,
            "Close": precios,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def test_cargar_datos_diarios_returns_same_shape_as_before(monkeypatch):
    fixture = _fixture_historial()

    with patch(
        "app.strategies.rsi2_connors.YahooProvider"
    ) as mock_provider_cls:
        mock_provider_cls.return_value.get_daily_history.return_value = fixture

        data = rsi2_connors._cargar_datos_diarios("AAPL")

    assert list(data.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(data) == len(fixture)
    mock_provider_cls.return_value.get_daily_history.assert_called_once_with(
        "AAPL", rsi2_connors.PERIODO_DESCARGA
    )


def test_cargar_datos_diarios_retries_via_yahoo_provider_backoff():
    """Integración de punta a punta: una falla transitoria en la fuente
    de datos (mockeada al nivel de yf.Ticker, no de YahooProvider) se
    resuelve por el reintento real de YahooProvider - _cargar_datos_diarios
    no necesita (ni tiene) su propia lógica de reintento."""
    fixture = _fixture_historial()
    mock_history = MagicMock(side_effect=[ConnectionError("falla transitoria"), fixture])

    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls, \
         patch("app.providers.yahoo_provider.time.sleep"):
        mock_ticker_cls.return_value.history = mock_history

        data = rsi2_connors._cargar_datos_diarios("AAPL")

    assert data is not None
    assert len(data) == len(fixture)
    # 1 falla + 1 éxito: no falló en el primer intento, el reintento real
    # de YahooProvider absorbió la falla transitoria.
    assert mock_history.call_count == 2


def test_cargar_datos_diarios_returns_none_on_permanent_failure():
    with patch("app.strategies.rsi2_connors.YahooProvider") as mock_provider_cls:
        mock_provider_cls.return_value.get_daily_history.side_effect = YahooProviderError(
            "sin datos"
        )

        resultado = rsi2_connors._cargar_datos_diarios("AAPL")

    assert resultado is None


def test_ejecutar_rsi2_connors_continues_to_next_symbol_on_permanent_failure(monkeypatch):
    """Un símbolo con falla permanente no debe detener el resto del
    universo (ya era así antes de este cambio - se confirma que sigue
    siéndolo con YahooProvider de por medio)."""
    universo_original = rsi2_connors.ACTIVOS
    monkeypatch.setattr(rsi2_connors, "ACTIVOS", ["ROTO", "OK"])

    llamados = []

    def fake_procesar_activo(activo, ahora):
        llamados.append(activo)
        if activo == "ROTO":
            raise YahooProviderError("sin datos para ROTO")

    monkeypatch.setattr(rsi2_connors, "procesar_activo", fake_procesar_activo)

    rsi2_connors.ejecutar_rsi2_connors()

    assert llamados == ["ROTO", "OK"]

    monkeypatch.setattr(rsi2_connors, "ACTIVOS", universo_original)
