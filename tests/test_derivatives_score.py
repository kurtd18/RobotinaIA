"""
Pruebas del score de derivados (Fase 7). Todo mockeado - no dependen de
Internet.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.providers.binance_provider import BinanceProviderError
from app.scoring.derivatives_score import calcular_score_derivados


def _df_precio(n=30, tendencia="subiendo"):
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    paso = 1.0 if tendencia == "subiendo" else (-1.0 if tendencia == "bajando" else 0.0)
    close = 100 + np.arange(n) * paso
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 100.0}, index=idx)


def _mock_provider(funding_rate=0.0001, oi_tendencia="subiendo", ls_ratio=1.0,
                    liquidaciones=None, precio_tendencia="subiendo"):
    provider = MagicMock()
    provider.get_ohlcv.return_value = _df_precio(tendencia=precio_tendencia)
    provider.get_funding_rate_history.return_value = [
        {"symbol": "BTCUSDT", "funding_rate": funding_rate, "funding_time": datetime.now(timezone.utc)}
    ]
    valores_oi = [1000.0, 1000.0, 1200.0, 1300.0] if oi_tendencia == "subiendo" else [1000.0, 1000.0, 800.0, 700.0]
    provider.get_open_interest_history.return_value = [
        {"symbol": "BTCUSDT", "open_interest": v, "time": datetime.now(timezone.utc)} for v in valores_oi
    ]
    provider.get_long_short_ratio.return_value = [
        {"symbol": "BTCUSDT", "long_short_ratio": ls_ratio, "long_account_pct": 0.5,
         "short_account_pct": 0.5, "time": datetime.now(timezone.utc)}
    ]
    provider.get_liquidation_orders.return_value = liquidaciones if liquidaciones is not None else []
    return provider


def test_funding_rate_alto_es_desfavorable():
    provider = _mock_provider(funding_rate=0.001)

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    fr = next(m for m in resultado["metricas"] if m["metrica"] == "funding_rate")
    assert fr["senal"] == "desfavorable"


def test_funding_rate_negativo_es_favorable():
    provider = _mock_provider(funding_rate=-0.001)

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    fr = next(m for m in resultado["metricas"] if m["metrica"] == "funding_rate")
    assert fr["senal"] == "favorable"


def test_oi_subiendo_con_precio_subiendo_es_favorable():
    provider = _mock_provider(oi_tendencia="subiendo", precio_tendencia="subiendo")

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    oi = next(m for m in resultado["metricas"] if m["metrica"] == "oi_precio_volumen")
    assert oi["senal"] == "favorable"


def test_oi_subiendo_con_precio_bajando_es_desfavorable():
    provider = _mock_provider(oi_tendencia="subiendo", precio_tendencia="bajando")

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    oi = next(m for m in resultado["metricas"] if m["metrica"] == "oi_precio_volumen")
    assert oi["senal"] == "desfavorable"


def test_oi_bajando_es_siempre_neutral_no_se_interpreta_aislado():
    provider_subida = _mock_provider(oi_tendencia="bajando", precio_tendencia="subiendo")
    provider_bajada = _mock_provider(oi_tendencia="bajando", precio_tendencia="bajando")

    r1 = calcular_score_derivados("BTCUSDT", provider=provider_subida)
    r2 = calcular_score_derivados("BTCUSDT", provider=provider_bajada)

    oi1 = next(m for m in r1["metricas"] if m["metrica"] == "oi_precio_volumen")
    oi2 = next(m for m in r2["metricas"] if m["metrica"] == "oi_precio_volumen")
    assert oi1["senal"] == "neutral"
    assert oi2["senal"] == "neutral"


def test_long_short_ratio_extremo_alto_es_desfavorable_contrarian():
    provider = _mock_provider(ls_ratio=2.0)

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    ls = next(m for m in resultado["metricas"] if m["metrica"] == "long_short_ratio")
    assert ls["senal"] == "desfavorable"


def test_long_short_ratio_extremo_bajo_es_favorable_contrarian():
    provider = _mock_provider(ls_ratio=0.5)

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    ls = next(m for m in resultado["metricas"] if m["metrica"] == "long_short_ratio")
    assert ls["senal"] == "favorable"


def test_liquidaciones_dominancia_cortos_es_favorable():
    liquidaciones = [{"side": "BUY"}] * 10 + [{"side": "SELL"}] * 2
    provider = _mock_provider(liquidaciones=liquidaciones)

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    liq = next(m for m in resultado["metricas"] if m["metrica"] == "liquidaciones")
    assert liq["senal"] == "favorable"


def test_liquidaciones_vacias_es_neutral_no_sin_datos():
    provider = _mock_provider(liquidaciones=[])

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    liq = next(m for m in resultado["metricas"] if m["metrica"] == "liquidaciones")
    assert liq["senal"] == "neutral"


def test_metrica_que_falla_queda_sin_datos_sin_tumbar_las_demas():
    provider = _mock_provider()
    provider.get_long_short_ratio.side_effect = BinanceProviderError("falla")

    resultado = calcular_score_derivados("BTCUSDT", provider=provider)

    ls = next(m for m in resultado["metricas"] if m["metrica"] == "long_short_ratio")
    assert ls["senal"] == "sin_datos"
    assert resultado["disponible"] is True  # las otras 3 sí tienen datos
