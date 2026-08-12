"""
Pruebas del score técnico (Fase 7). Todo mockeado sobre BinanceProvider
- no dependen de Internet. Se usan series de precios sintéticas
estrictamente monótonas para producir señales técnicas predecibles.
"""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.providers.binance_provider import BinanceProviderError
from app.scoring.technical_score import calcular_score_tecnico, calcular_score_timeframe


def _df_tendencia(n=260, alcista=True, volumen_final_alto=True):
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    paso = 0.5 if alcista else -0.5
    close = 100 + np.arange(n) * paso
    volumen = np.full(n, 1000.0)
    if volumen_final_alto:
        volumen[-1] = 5000.0

    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.2,
            "Low": close - 0.2,
            "Close": close,
            "Volume": volumen,
        },
        index=idx,
    )


def _mock_provider(df):
    provider = MagicMock()
    provider.get_ohlcv.return_value = df
    return provider


def test_timeframe_tendencia_alcista_da_score_alto():
    provider = _mock_provider(_df_tendencia(alcista=True))

    resultado = calcular_score_timeframe("BTCUSDT", "1h", provider=provider)

    assert resultado["disponible"] is True
    # con tendencia claramente alcista, casi todas las métricas dan favorable
    assert resultado["puntos"] > 0.7


def test_timeframe_tendencia_bajista_da_score_bajo():
    provider = _mock_provider(_df_tendencia(alcista=False))

    resultado = calcular_score_timeframe("BTCUSDT", "1h", provider=provider)

    assert resultado["puntos"] < 0.3


def test_timeframe_metricas_incluyen_atr_siempre_neutral():
    provider = _mock_provider(_df_tendencia(alcista=True))

    resultado = calcular_score_timeframe("BTCUSDT", "1h", provider=provider)

    atr = next(m for m in resultado["metricas"] if m["metrica"] == "atr")
    assert atr["senal"] == "neutral"
    assert atr["valor"] is not None


def test_score_tecnico_combina_tres_timeframes_con_pesos():
    provider = _mock_provider(_df_tendencia(alcista=True))

    resultado = calcular_score_tecnico("BTCUSDT", provider=provider)

    assert resultado["disponible"] is True
    assert resultado["puntos"] > 21  # 30 * 0.7 aprox, tendencia alcista fuerte
    assert set(resultado["por_timeframe"].keys()) == {"4h", "1h", "15m"}


def test_score_tecnico_redistribuye_peso_si_un_timeframe_falla():
    provider = MagicMock()

    def get_ohlcv(symbol, interval, num_velas=100):
        if interval == "15m":
            raise BinanceProviderError("sin datos")
        return _df_tendencia(alcista=True)

    provider.get_ohlcv.side_effect = get_ohlcv

    resultado = calcular_score_tecnico("BTCUSDT", provider=provider)

    assert resultado["disponible"] is True
    assert resultado["por_timeframe"]["15m"]["disponible"] is False
    assert resultado["por_timeframe"]["4h"]["disponible"] is True


def test_score_tecnico_todos_los_timeframes_fallan_queda_no_disponible():
    provider = MagicMock()
    provider.get_ohlcv.side_effect = BinanceProviderError("sin datos")

    resultado = calcular_score_tecnico("BTCUSDT", provider=provider)

    assert resultado["disponible"] is False
    assert resultado["puntos"] is None
