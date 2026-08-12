"""
Pruebas del módulo de análisis on-chain de BTC. Todo mockeado - no
dependen de Internet.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.onchain.btc_onchain import (
    METRICAS_BLOCKCHAIN_INFO,
    METRICAS_NO_DISPONIBLES,
    calcular_metrica,
    calcular_nvt,
    calcular_onchain_btc,
)
from app.onchain.providers.blockchain_info_provider import BlockchainInfoProviderError


def _historial(valores):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"timestamp": base, "valor": v} for v in valores]


def _mock_provider(historial_por_chart=None, error_en=None):
    provider = MagicMock()

    def get_chart(chart_key, timespan="30days"):
        if error_en and chart_key in error_en:
            raise BlockchainInfoProviderError(f"sin datos {chart_key}")
        return (historial_por_chart or {}).get(chart_key, _historial([100.0, 100.0, 105.0, 110.0]))

    provider.get_chart.side_effect = get_chart
    return provider


def test_calcular_metrica_nombre_invalido():
    with pytest.raises(ValueError):
        calcular_metrica("no-existe")


def test_calcular_metrica_estructura_esperada():
    provider = _mock_provider()

    resultado = calcular_metrica("direcciones_activas", provider=provider)

    assert set(resultado.keys()) == {
        "metrica", "valor", "unidad", "timestamp", "fuente", "tendencia", "estado"
    }
    assert resultado["metrica"] == "direcciones_activas"
    assert resultado["tendencia"] == "subiendo"
    assert resultado["estado"] == "favorable"  # sube_favorable + subiendo


def test_calcular_metrica_polaridad_neutral_no_produce_favorable_ni_desfavorable():
    provider = _mock_provider(historial_por_chart={
        "suministro": _historial([100.0, 100.0, 105.0, 110.0])
    })

    resultado = calcular_metrica("suministro", provider=provider)

    assert resultado["estado"] == "neutral"


def test_calcular_metrica_error_propaga():
    provider = _mock_provider(error_en={"hash_rate"})

    with pytest.raises(BlockchainInfoProviderError):
        calcular_metrica("hash_rate", provider=provider)


def test_calcular_nvt_ok():
    provider = _mock_provider(historial_por_chart={
        "market_cap": _historial([1_000_000.0, 1_000_000.0, 1_100_000.0, 1_100_000.0]),
        "volumen_transacciones_usd": _historial([100_000.0, 100_000.0, 100_000.0, 100_000.0]),
    })

    resultado = calcular_nvt(provider=provider)

    assert resultado["metrica"] == "nvt"
    assert resultado["valor"] == pytest.approx(11.0)
    assert resultado["tendencia"] == "subiendo"
    assert resultado["estado"] == "desfavorable"  # sube_desfavorable + subiendo


def test_calcular_onchain_btc_incluye_disponibles_y_no_disponibles():
    provider = _mock_provider()

    resultados = calcular_onchain_btc(provider=provider)
    nombres = [r["metrica"] for r in resultados]

    for nombre in METRICAS_BLOCKCHAIN_INFO:
        assert nombre in nombres
    assert "nvt" in nombres
    for nombre in METRICAS_NO_DISPONIBLES:
        assert nombre in nombres

    no_disponibles = [r for r in resultados if r["metrica"] in METRICAS_NO_DISPONIBLES]
    for r in no_disponibles:
        assert r["valor"] is None
        assert r["estado"] == "sin_datos"


def test_calcular_onchain_btc_metrica_que_falla_queda_como_no_disponible():
    provider = _mock_provider(error_en={"hash_rate"})

    resultados = calcular_onchain_btc(provider=provider)
    hash_rate = next(r for r in resultados if r["metrica"] == "hash_rate")

    assert hash_rate["valor"] is None
    assert hash_rate["estado"] == "sin_datos"
