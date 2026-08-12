"""
Pruebas del score fundamental (Fase 7). Todo mockeado sobre los módulos
de Fase 6 - no dependen de Internet.
"""

from unittest.mock import patch

import pytest

from app.scoring.fundamental_score import calcular_score_fundamental, METRICAS_BTC, METRICAS_ETH


def _metrica_btc(nombre, estado):
    return {"metrica": nombre, "valor": 1.0, "unidad": "u", "timestamp": None,
            "fuente": "test", "tendencia": "estable", "estado": estado}


@patch("app.scoring.fundamental_score.calcular_onchain_btc")
def test_score_fundamental_btc_usa_solo_metricas_esperadas(mock_onchain):
    mock_onchain.return_value = [_metrica_btc(n, "favorable") for n in METRICAS_BTC]
    mock_onchain.return_value.append(_metrica_btc("mvrv", "sin_datos"))  # no debe influir

    resultado = calcular_score_fundamental("BTCUSDT")

    nombres = [m["metrica"] for m in resultado["metricas"]]
    assert set(nombres) == set(METRICAS_BTC)
    assert resultado["puntos"] == pytest.approx(30.0)


@patch("app.scoring.fundamental_score.calcular_onchain_btc")
def test_score_fundamental_btc_metrica_faltante_en_lista_no_rompe(mock_onchain):
    # Fase 6 no devuelve "dificultad" por alguna razón
    incompleta = [_metrica_btc(n, "favorable") for n in METRICAS_BTC if n != "dificultad"]
    mock_onchain.return_value = incompleta

    resultado = calcular_score_fundamental("BTCUSDT")

    dificultad = next(m for m in resultado["metricas"] if m["metrica"] == "dificultad")
    assert dificultad["senal"] == "sin_datos"


@patch("app.scoring.fundamental_score.calcular_onchain_eth")
def test_score_fundamental_eth_agrega_tvl_l2_total_por_mayoria(mock_onchain):
    base = [_metrica_btc(n, "favorable") for n in METRICAS_ETH]
    mock_onchain.return_value = base

    resultado = calcular_score_fundamental("ETHUSDT")

    nombres = [m["metrica"] for m in resultado["metricas"]]
    assert "tvl_l2_total" in nombres
    tvl_l2_total = next(m for m in resultado["metricas"] if m["metrica"] == "tvl_l2_total")
    assert tvl_l2_total["senal"] == "favorable"  # los 3 L2 son favorables


def test_score_fundamental_activo_sin_onchain_propio_queda_sin_datos_no_falla():
    resultado = calcular_score_fundamental("SOLUSDT")

    assert resultado["disponible"] is False
    assert resultado["puntos"] is None
    assert resultado["metricas"] == []
