"""
Métricas descriptivas de derivados para cripto (BTC/USDT, ETH/USDT):
funding rate y open interest, con historial y tendencia.

Fase 3 de RobotinaIA Crypto: solo calcula y expone valores descriptivos
(promedio, variación, tendencia). No genera señales ni un sub-score -
eso es una fase posterior (scoring, 20% del análisis final).
"""

from loguru import logger

from app.providers.binance_provider import BinanceProvider

FUNDING_RATE_HISTORIAL_DEFECTO = 30
OPEN_INTEREST_HISTORIAL_DEFECTO = 30
OPEN_INTEREST_PERIODO_DEFECTO = "4h"

# Diferencia mínima (en % relativo) para no considerar la tendencia
# "estable" por simple ruido numérico.
UMBRAL_TENDENCIA_PCT = 1.0


def _tendencia(valor_reciente: float, valor_previo: float) -> str:
    if valor_previo == 0:
        return "estable"

    variacion_pct = (valor_reciente - valor_previo) / abs(valor_previo) * 100

    if variacion_pct > UMBRAL_TENDENCIA_PCT:
        return "subiendo"
    if variacion_pct < -UMBRAL_TENDENCIA_PCT:
        return "bajando"
    return "estable"


def _partir_en_mitades(valores: list[float]):
    """Divide una serie ordenada cronológicamente en dos mitades, para
    comparar el promedio reciente contra el promedio previo."""
    mitad = len(valores) // 2
    if mitad == 0:
        return valores, valores
    return valores[:mitad], valores[mitad:]


def calcular_funding_rate(symbol: str, provider: BinanceProvider = None,
                           limit: int = FUNDING_RATE_HISTORIAL_DEFECTO) -> dict:
    """
    Devuelve funding rate actual, promedio del historial y tendencia:
    {
        "symbol", "funding_rate_actual", "funding_rate_promedio",
        "funding_rate_tendencia", "historial": [...]
    }
    """
    provider = provider or BinanceProvider()

    logger.info(f"Calculando funding rate {symbol} (historial={limit})...")
    historial = provider.get_funding_rate_history(symbol, limit=limit)

    tasas = [item["funding_rate"] for item in historial]
    previas, recientes = _partir_en_mitades(tasas)

    resultado = {
        "symbol": symbol,
        "funding_rate_actual": historial[-1]["funding_rate"],
        "funding_rate_promedio": sum(tasas) / len(tasas),
        "funding_rate_tendencia": _tendencia(
            sum(recientes) / len(recientes), sum(previas) / len(previas)
        ),
        "historial": historial,
    }
    logger.info(
        f"OK: funding rate {symbol} actual={resultado['funding_rate_actual']:.6f} "
        f"promedio={resultado['funding_rate_promedio']:.6f} "
        f"tendencia={resultado['funding_rate_tendencia']}"
    )
    return resultado


def calcular_open_interest(symbol: str, provider: BinanceProvider = None,
                            period: str = OPEN_INTEREST_PERIODO_DEFECTO,
                            limit: int = OPEN_INTEREST_HISTORIAL_DEFECTO) -> dict:
    """
    Devuelve open interest actual, promedio del historial y tendencia:
    {
        "symbol", "open_interest_actual", "open_interest_promedio",
        "open_interest_variacion_pct", "open_interest_tendencia", "historial": [...]
    }
    """
    provider = provider or BinanceProvider()

    logger.info(f"Calculando open interest {symbol} (period={period}, historial={limit})...")
    historial = provider.get_open_interest_history(symbol, period=period, limit=limit)

    valores = [item["open_interest"] for item in historial]
    previos, recientes = _partir_en_mitades(valores)
    promedio_reciente = sum(recientes) / len(recientes)
    promedio_previo = sum(previos) / len(previos)

    variacion_pct = (
        (promedio_reciente - promedio_previo) / abs(promedio_previo) * 100
        if promedio_previo != 0 else 0.0
    )

    resultado = {
        "symbol": symbol,
        "open_interest_actual": historial[-1]["open_interest"],
        "open_interest_promedio": sum(valores) / len(valores),
        "open_interest_variacion_pct": variacion_pct,
        "open_interest_tendencia": _tendencia(promedio_reciente, promedio_previo),
        "historial": historial,
    }
    logger.info(
        f"OK: open interest {symbol} actual={resultado['open_interest_actual']} "
        f"variacion={resultado['open_interest_variacion_pct']:.2f}% "
        f"tendencia={resultado['open_interest_tendencia']}"
    )
    return resultado


def calcular_derivados(symbol: str, provider: BinanceProvider = None) -> dict:
    """Combina funding rate y open interest para `symbol` en un solo dict."""
    provider = provider or BinanceProvider()

    return {
        "symbol": symbol,
        "funding_rate": calcular_funding_rate(symbol, provider),
        "open_interest": calcular_open_interest(symbol, provider),
    }
