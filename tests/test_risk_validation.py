"""
Pruebas del validador de riesgo/beneficio (Fase 7). Todo mockeado - no
dependen de Internet.
"""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.providers.binance_provider import BinanceProviderError
from app.scoring.risk_validation import RATIO_MINIMO, calcular_risk_reward


def _df_1h(precio_actual=100.0, atr_aprox=1.0, n=50):
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    close = np.full(n, precio_actual)
    high = close + atr_aprox
    low = close - atr_aprox
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close,
                          "Volume": 100.0}, index=idx)


def _df_4h(high_max=110.0, low_min=90.0, n=20):
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    close = np.linspace(95, 105, n)
    return pd.DataFrame({
        "Open": close, "High": np.linspace(96, high_max, n),
        "Low": np.linspace(low_min, 94, n), "Close": close, "Volume": 100.0,
    }, index=idx)


def _mock_provider(precio_actual=100.0, atr_aprox=1.0, high_max=110.0, low_min=90.0):
    provider = MagicMock()

    def get_ohlcv(symbol, interval, num_velas=100):
        if interval == "1h":
            return _df_1h(precio_actual, atr_aprox)
        return _df_4h(high_max, low_min)

    provider.get_ohlcv.side_effect = get_ohlcv
    return provider


def test_long_ratio_favorable_cumple_minimo():
    # target lejos (resistencia en 110, entry ~100), stop cerca (ATR chico)
    provider = _mock_provider(precio_actual=100.0, atr_aprox=0.5, high_max=115.0)

    resultado = calcular_risk_reward("BTCUSDT", "LONG", provider=provider)

    assert resultado["disponible"] is True
    assert resultado["ratio"] > RATIO_MINIMO
    assert resultado["cumple_minimo"] is True


def test_long_ratio_desfavorable_no_cumple_minimo():
    # target cerca, stop lejos (ATR grande)
    provider = _mock_provider(precio_actual=100.0, atr_aprox=10.0, high_max=101.0)

    resultado = calcular_risk_reward("BTCUSDT", "LONG", provider=provider)

    assert resultado["disponible"] is True
    assert resultado["cumple_minimo"] is False


def test_short_usa_soporte_como_target():
    provider = _mock_provider(precio_actual=100.0, atr_aprox=0.5, low_min=80.0)

    resultado = calcular_risk_reward("BTCUSDT", "SHORT", provider=provider)

    assert resultado["disponible"] is True
    assert resultado["target"] < resultado["entry"]


def test_direccion_invalida():
    provider = _mock_provider()
    with pytest.raises(ValueError):
        calcular_risk_reward("BTCUSDT", "HOLD", provider=provider)


def test_provider_falla_no_disponible_y_no_cumple_por_fail_safe():
    provider = MagicMock()
    provider.get_ohlcv.side_effect = BinanceProviderError("sin datos")

    resultado = calcular_risk_reward("BTCUSDT", "LONG", provider=provider)

    assert resultado["disponible"] is False
    assert resultado["cumple_minimo"] is False  # fail-safe: nunca asume que cumple
