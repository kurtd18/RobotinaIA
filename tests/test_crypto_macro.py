"""
Pruebas de MacroProvider y del módulo de contexto macro. Todo mockeado
- no dependen de Internet.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.macro.crypto_macro import calcular_contexto_macro, calcular_indicador_macro
from app.macro.macro_provider import MacroProvider, MacroProviderError, TICKERS_MACRO


def _df_close(valores):
    idx = pd.date_range("2026-01-01", periods=len(valores), freq="D")
    return pd.DataFrame({"Close": valores}, index=idx)


# ---------- MacroProvider ----------

@patch("app.macro.macro_provider.yf.Ticker")
def test_get_history_ok(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _df_close([100.0, 101.0, 102.0])
    mock_ticker_cls.return_value = mock_ticker

    provider = MacroProvider()
    df = provider.get_history("^TNX")

    assert list(df["Close"]) == [100.0, 101.0, 102.0]
    mock_ticker_cls.assert_called_once_with("^TNX")


@patch("app.macro.macro_provider.yf.Ticker")
def test_get_history_vacio_lanza_error(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_ticker

    provider = MacroProvider()
    with pytest.raises(MacroProviderError):
        provider.get_history("^TNX")


@patch("app.macro.macro_provider.yf.Ticker")
def test_get_history_excepcion_de_yfinance_se_propaga_como_macro_error(mock_ticker_cls):
    mock_ticker_cls.side_effect = RuntimeError("fallo de red")

    provider = MacroProvider()
    with pytest.raises(MacroProviderError):
        provider.get_history("^TNX")


# ---------- crypto_macro: calcular_indicador_macro ----------

def _mock_provider(cierres):
    provider = MagicMock()
    provider.get_history.return_value = _df_close(cierres)
    return provider


def test_calcular_indicador_macro_nombre_invalido():
    with pytest.raises(ValueError):
        calcular_indicador_macro("EURUSD")


def test_calcular_indicador_macro_tendencia_subiendo():
    provider = _mock_provider([100.0, 100.0, 105.0, 106.0])

    resultado = calcular_indicador_macro("DXY", provider=provider)

    assert resultado["ticker"] == TICKERS_MACRO["DXY"]
    assert resultado["valor_actual"] == pytest.approx(106.0)
    assert resultado["tendencia"] == "subiendo"


def test_calcular_indicador_macro_tendencia_estable():
    provider = _mock_provider([100.0, 100.1, 99.9, 100.0])

    resultado = calcular_indicador_macro("US10Y", provider=provider)

    assert resultado["tendencia"] == "estable"


# ---------- crypto_macro: calcular_contexto_macro ----------

def test_calcular_contexto_macro_incluye_los_cuatro_indicadores():
    provider = MagicMock()
    provider.get_history.return_value = _df_close([100.0, 101.0])

    resultado = calcular_contexto_macro(provider=provider)

    assert set(resultado.keys()) == set(TICKERS_MACRO.keys())


def test_calcular_contexto_macro_excluye_el_indicador_que_falla():
    provider = MagicMock()

    def get_history(ticker, period="1mo", interval="1d"):
        if ticker == TICKERS_MACRO["GOLD"]:
            raise MacroProviderError("sin datos")
        return _df_close([100.0, 101.0])

    provider.get_history.side_effect = get_history

    resultado = calcular_contexto_macro(provider=provider)

    assert "GOLD" not in resultado
    assert set(resultado.keys()) == set(TICKERS_MACRO.keys()) - {"GOLD"}
