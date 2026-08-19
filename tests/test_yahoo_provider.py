"""Tests de app/providers/yahoo_provider.py."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.providers.yahoo_provider import (
    MAX_REINTENTOS,
    YahooProvider,
    YahooProviderError,
)


def _df_con_precio(precio: float) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=1, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"Open": [precio], "High": [precio], "Low": [precio], "Close": [precio], "Volume": [1.0]},
        index=idx,
    )


def test_get_stock_returns_stock_with_positive_price():
    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.history.return_value = _df_con_precio(150.25)

        stock = YahooProvider().get_stock("AAPL")

        assert stock.symbol == "AAPL"
        assert stock.price == 150.25
        assert stock.price > 0


def test_retries_on_transient_exception_and_succeeds_on_third_call():
    mock_history = MagicMock(
        side_effect=[
            ConnectionError("falla de red 1"),
            ConnectionError("falla de red 2"),
            _df_con_precio(100.0),
        ]
    )
    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls, \
         patch("app.providers.yahoo_provider.time.sleep"):
        mock_ticker_cls.return_value.history = mock_history

        stock = YahooProvider().get_stock("AAPL")

        assert stock.price == 100.0
        assert mock_history.call_count == 3


def test_raises_yahoo_provider_error_after_max_retries_on_permanent_failure():
    mock_history = MagicMock(side_effect=ConnectionError("siempre falla"))
    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls, \
         patch("app.providers.yahoo_provider.time.sleep"):
        mock_ticker_cls.return_value.history = mock_history

        with pytest.raises(YahooProviderError):
            YahooProvider().get_stock("AAPL")

        assert mock_history.call_count == MAX_REINTENTOS


def test_empty_dataframe_raises_yahoo_provider_error():
    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.history.return_value = pd.DataFrame()

        with pytest.raises(YahooProviderError):
            YahooProvider().get_stock("AAPL")


def test_get_daily_history_returns_the_dataframe():
    df_esperado = _df_con_precio(200.0)
    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.history.return_value = df_esperado

        df = YahooProvider().get_daily_history("AAPL", "2y")

        assert df.equals(df_esperado)
        mock_ticker_cls.return_value.history.assert_called_once_with(period="2y", interval="1d")
