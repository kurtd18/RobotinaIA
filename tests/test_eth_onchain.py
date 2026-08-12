"""
Pruebas del módulo de análisis on-chain de ETH. Todo mockeado - no
dependen de Internet.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.onchain.eth_onchain import (
    CHAINS_L2,
    METRICAS_NO_DISPONIBLES,
    calcular_onchain_eth,
    calcular_suministro,
    calcular_tvl,
)
from app.onchain.providers.defillama_provider import DefiLlamaProviderError


def _tvl_historial(valores):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"timestamp": base, "tvl_usd": v} for v in valores]


def test_calcular_tvl_estructura_y_tendencia():
    provider = MagicMock()
    provider.get_chain_tvl_history.return_value = _tvl_historial([100.0, 100.0, 120.0, 130.0])

    resultado = calcular_tvl("tvl_defi_ethereum", "Ethereum", provider=provider)

    assert set(resultado.keys()) == {
        "metrica", "valor", "unidad", "timestamp", "fuente", "tendencia", "estado"
    }
    assert resultado["tendencia"] == "subiendo"
    assert resultado["estado"] == "favorable"


def test_calcular_tvl_bajando_es_desfavorable():
    provider = MagicMock()
    provider.get_chain_tvl_history.return_value = _tvl_historial([100.0, 100.0, 70.0, 60.0])

    resultado = calcular_tvl("tvl_l2_arbitrum", "Arbitrum", provider=provider)

    assert resultado["tendencia"] == "bajando"
    assert resultado["estado"] == "desfavorable"


def test_calcular_suministro_sin_tendencia_por_ser_snapshot():
    provider = MagicMock()
    provider.get_supply.return_value = {
        "coin_id": "ethereum", "circulating_supply": 120_500_000.0,
        "total_supply": 120_500_000.0, "market_cap_usd": 400_000_000_000.0,
    }

    resultado = calcular_suministro(provider=provider)

    assert resultado["valor"] == 120_500_000.0
    assert resultado["tendencia"] == "sin_datos"
    assert resultado["estado"] == "neutral"


def test_calcular_onchain_eth_incluye_tvl_suministro_y_no_disponibles():
    defillama = MagicMock()
    defillama.get_chain_tvl_history.return_value = _tvl_historial([100.0, 110.0])
    coingecko = MagicMock()
    coingecko.get_supply.return_value = {
        "coin_id": "ethereum", "circulating_supply": 120_000_000.0,
        "total_supply": 120_000_000.0, "market_cap_usd": 400_000_000_000.0,
    }

    resultados = calcular_onchain_eth(defillama_provider=defillama, coingecko_provider=coingecko)
    nombres = [r["metrica"] for r in resultados]

    assert "tvl_defi_ethereum" in nombres
    for chain in CHAINS_L2:
        assert f"tvl_l2_{chain.lower()}" in nombres
    assert "suministro" in nombres
    for nombre in METRICAS_NO_DISPONIBLES:
        assert nombre in nombres

    no_disponibles = [r for r in resultados if r["metrica"] in METRICAS_NO_DISPONIBLES]
    for r in no_disponibles:
        assert r["valor"] is None
        assert r["estado"] == "sin_datos"


def test_calcular_onchain_eth_tvl_que_falla_queda_como_no_disponible():
    defillama = MagicMock()

    def get_history(chain):
        if chain == "Ethereum":
            raise DefiLlamaProviderError("sin datos")
        return _tvl_historial([100.0, 110.0])

    defillama.get_chain_tvl_history.side_effect = get_history

    coingecko = MagicMock()
    coingecko.get_supply.return_value = {
        "coin_id": "ethereum", "circulating_supply": 120_000_000.0,
        "total_supply": 120_000_000.0, "market_cap_usd": 400_000_000_000.0,
    }

    resultados = calcular_onchain_eth(defillama_provider=defillama, coingecko_provider=coingecko)
    tvl_eth = next(r for r in resultados if r["metrica"] == "tvl_defi_ethereum")

    assert tvl_eth["valor"] is None
    assert tvl_eth["estado"] == "sin_datos"
