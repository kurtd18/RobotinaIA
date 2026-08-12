"""
Pruebas del score de sentimiento y macro (Fase 7). Todo mockeado - no
dependen de Internet.
"""

from unittest.mock import MagicMock

import pytest

from app.scoring.macro_score import calcular_score_macro
from app.scoring.sentiment_score import calcular_score_sentimiento
from app.sentiment.fear_greed_provider import FearGreedProviderError


def _mock_sentiment_provider(valores):
    provider = MagicMock()
    provider.get_index_history.return_value = [
        {"valor": v, "clasificacion": "x", "timestamp": None} for v in valores
    ]
    return provider


def test_sentimiento_miedo_extremo_es_favorable():
    provider = _mock_sentiment_provider([15, 15, 15, 15])

    resultado = calcular_score_sentimiento(provider=provider)

    actual = next(m for m in resultado["metricas"] if m["metrica"] == "valor_actual")
    assert actual["senal"] == "favorable"


def test_sentimiento_codicia_extrema_es_desfavorable():
    provider = _mock_sentiment_provider([85, 85, 85, 85])

    resultado = calcular_score_sentimiento(provider=provider)

    actual = next(m for m in resultado["metricas"] if m["metrica"] == "valor_actual")
    assert actual["senal"] == "desfavorable"


def test_sentimiento_neutral_en_zona_media():
    provider = _mock_sentiment_provider([50, 50, 50, 50])

    resultado = calcular_score_sentimiento(provider=provider)

    actual = next(m for m in resultado["metricas"] if m["metrica"] == "valor_actual")
    assert actual["senal"] == "neutral"


def test_sentimiento_tendencia_siempre_neutral():
    provider = _mock_sentiment_provider([10, 10, 90, 90])

    resultado = calcular_score_sentimiento(provider=provider)

    tendencia = next(m for m in resultado["metricas"] if m["metrica"] == "tendencia")
    assert tendencia["senal"] == "neutral"


def test_sentimiento_provider_falla_queda_sin_datos():
    provider = MagicMock()
    provider.get_index_history.side_effect = FearGreedProviderError("falla")

    resultado = calcular_score_sentimiento(provider=provider)

    assert resultado["disponible"] is False


def _mock_macro_provider(tendencias: dict):
    from app.macro.macro_provider import TICKERS_MACRO
    provider = MagicMock()

    def get_history(ticker, period="1mo", interval="1d"):
        import pandas as pd
        nombre = next(n for n, t in TICKERS_MACRO.items() if t == ticker)
        tendencia = tendencias.get(nombre, "estable")
        valores = {"subiendo": [100.0, 100.0, 110.0], "bajando": [100.0, 100.0, 90.0],
                   "estable": [100.0, 100.0, 100.0]}[tendencia]
        idx = pd.date_range("2026-01-01", periods=len(valores), freq="D")
        return pd.DataFrame({"Close": valores}, index=idx)

    provider.get_history.side_effect = get_history
    return provider


def test_macro_dxy_subiendo_es_desfavorable():
    provider = _mock_macro_provider({"DXY": "subiendo"})

    resultado = calcular_score_macro(provider=provider)

    dxy = next(m for m in resultado["metricas"] if m["metrica"] == "DXY")
    assert dxy["senal"] == "desfavorable"


def test_macro_sp500_subiendo_es_favorable():
    provider = _mock_macro_provider({"SP500": "subiendo"})

    resultado = calcular_score_macro(provider=provider)

    sp500 = next(m for m in resultado["metricas"] if m["metrica"] == "SP500")
    assert sp500["senal"] == "favorable"


def test_macro_gold_siempre_neutral():
    provider = _mock_macro_provider({"GOLD": "subiendo"})

    resultado = calcular_score_macro(provider=provider)

    gold = next(m for m in resultado["metricas"] if m["metrica"] == "GOLD")
    assert gold["senal"] == "neutral"
