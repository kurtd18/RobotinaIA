"""
Métricas descriptivas de sentimiento de mercado cripto, vía Fear & Greed
Index (alternative.me).

Fase 4 de RobotinaIA Crypto: solo calcula y expone valores descriptivos
(valor actual, clasificación, promedio, tendencia). No genera señales ni
un sub-score - eso es una fase posterior (scoring, 10% del análisis
final). El índice es de todo el mercado cripto, no específico de
BTC/USDT ni ETH/USDT - se usa igual para ambos activos.
"""

from loguru import logger

from app.sentiment.fear_greed_provider import FearGreedProvider

HISTORIAL_DEFECTO = 30

UMBRAL_TENDENCIA_PUNTOS = 3


def _tendencia(valor_reciente: float, valor_previo: float) -> str:
    diferencia = valor_reciente - valor_previo

    if diferencia > UMBRAL_TENDENCIA_PUNTOS:
        return "subiendo"
    if diferencia < -UMBRAL_TENDENCIA_PUNTOS:
        return "bajando"
    return "estable"


def _partir_en_mitades(valores: list):
    mitad = len(valores) // 2
    if mitad == 0:
        return valores, valores
    return valores[:mitad], valores[mitad:]


def calcular_sentimiento(provider: FearGreedProvider = None, limit: int = HISTORIAL_DEFECTO) -> dict:
    """
    Devuelve el estado del sentimiento de mercado (Fear & Greed Index):
    {
        "valor_actual", "clasificacion_actual", "valor_promedio",
        "tendencia", "historial": [...]
    }
    """
    provider = provider or FearGreedProvider()

    logger.info(f"Calculando sentimiento de mercado (historial={limit})...")
    historial = provider.get_index_history(limit=limit)

    valores = [item["valor"] for item in historial]
    previos, recientes = _partir_en_mitades(valores)

    resultado = {
        "valor_actual": historial[-1]["valor"],
        "clasificacion_actual": historial[-1]["clasificacion"],
        "valor_promedio": sum(valores) / len(valores),
        "tendencia": _tendencia(
            sum(recientes) / len(recientes), sum(previos) / len(previos)
        ),
        "historial": historial,
    }
    logger.info(
        f"OK: sentimiento actual={resultado['valor_actual']} "
        f"({resultado['clasificacion_actual']}) "
        f"promedio={resultado['valor_promedio']:.1f} tendencia={resultado['tendencia']}"
    )
    return resultado
