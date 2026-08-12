"""
Pruebas de los indicadores técnicos cripto. Todo mockeado sobre
BinanceProvider - no dependen de Internet.
"""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.indicators.crypto_indicators import (
    TIMEFRAMES,
    calcular_indicadores,
    calcular_indicadores_multi_timeframe,
)
from app.providers.binance_provider import BinanceProviderError


def _df_ohlcv(n=60):
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame(
        {
            "Open": close + rng.normal(0, 0.1, n),
            "High": close + abs(rng.normal(0, 0.5, n)),
            "Low": close - abs(rng.normal(0, 0.5, n)),
            "Close": close,
            "Volume": abs(rng.normal(1000, 100, n)),
        },
        index=idx,
    )


def _mock_provider(df_por_intervalo=None, error_en=None):
    provider = MagicMock()

    def get_ohlcv(symbol, interval, num_velas=100):
        if error_en and interval in error_en:
            raise BinanceProviderError(f"sin datos {symbol} {interval}")
        return (df_por_intervalo or {}).get(interval, _df_ohlcv())

    provider.get_ohlcv.side_effect = get_ohlcv
    return provider


def test_calcular_indicadores_agrega_columnas_esperadas():
    provider = _mock_provider()

    data = calcular_indicadores("BTCUSDT", "15m", provider=provider)

    for columna in ("RSI", "EMA9", "EMA21", "VWAP", "MOM14", "ATR", "VOL_AVG"):
        assert columna in data.columns
    provider.get_ohlcv.assert_called_once_with("BTCUSDT", "15m", num_velas=100)


def test_calcular_indicadores_propaga_error_del_provider():
    provider = _mock_provider(error_en={"1h"})

    with pytest.raises(BinanceProviderError):
        calcular_indicadores("BTCUSDT", "1h", provider=provider)


def test_multi_timeframe_devuelve_los_tres_timeframes():
    provider = _mock_provider()

    resultado = calcular_indicadores_multi_timeframe("ETHUSDT", provider=provider)

    assert set(resultado.keys()) == set(TIMEFRAMES)
    for interval in TIMEFRAMES:
        assert "RSI" in resultado[interval].columns


def test_multi_timeframe_excluye_el_timeframe_que_falla_sin_tumbar_los_demas():
    provider = _mock_provider(error_en={"4h"})

    resultado = calcular_indicadores_multi_timeframe("BTCUSDT", provider=provider)

    assert set(resultado.keys()) == {"15m", "1h"}
    assert "4h" not in resultado


def test_calcular_indicadores_no_modifica_el_dataframe_original_del_provider():
    df_original = _df_ohlcv()
    provider = _mock_provider(df_por_intervalo={"15m": df_original})

    calcular_indicadores("BTCUSDT", "15m", provider=provider)

    assert "RSI" not in df_original.columns
