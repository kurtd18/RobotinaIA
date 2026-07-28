"""
Pruebas del motor de scoring real (scoring.calcular_score).

No usa red: construye datos OHLCV sintéticos con un índice de fecha
válido (igual formato al que devuelve yfinance.history()).
"""

import pandas as pd

from scoring import calcular_score


def _datos_ohlcv(precios, volumenes=None):
    n = len(precios)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min")
    precios_arr = pd.Series(precios).values

    if volumenes is None:
        volumenes = [1000] * n

    return pd.DataFrame(
        {
            "Open": precios_arr,
            "High": precios_arr + 1,
            "Low": precios_arr - 1,
            "Close": precios_arr,
            "Volume": volumenes,
        },
        index=idx,
    )


def test_calcular_score_devuelve_entero_entre_0_y_100():
    precios = [100 + i * 0.5 for i in range(60)]
    data = _datos_ohlcv(precios)

    score, precio = calcular_score(data)

    assert isinstance(score, int)
    assert 0 <= score <= 100
    assert precio == precios[-1]


def test_tendencia_alcista_con_volumen_creciente_da_score_alto():
    precios = [100 + i for i in range(60)]
    volumenes = [1000 + i * 100 for i in range(60)]
    data = _datos_ohlcv(precios, volumenes)

    score, _ = calcular_score(data)

    assert score >= 80


def test_precio_plano_solo_suma_temporal_y_atr_relativo():
    """Con precio de cierre plano, ningún indicador de tendencia/momentum
    dispara (RSI/EMA/VWAP/MACD/Volumen), pero el rango High/Low fijo (±1)
    de estos datos sintéticos sí representa una volatilidad relativa real
    (~2% del precio), así que el ATR relativo sí se cumple."""

    precios = [100.0] * 60
    data = _datos_ohlcv(precios)

    score, _ = calcular_score(data)

    assert score == 10


def test_tendencia_bajista_da_score_bajo():
    precios = [160 - i for i in range(60)]
    data = _datos_ohlcv(precios)

    score, _ = calcular_score(data)

    assert score < 50