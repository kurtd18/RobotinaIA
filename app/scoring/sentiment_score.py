"""
Score de sentimiento (10 puntos) del CryptoScoringEngine.

Reutiliza app/sentiment/crypto_sentiment.py (Fase 4). Reglas explícitas
(lectura contrarian del Fear & Greed Index, estándar en cripto):
- valor_actual: <= 25 (Extreme Fear) => favorable; >= 75 (Extreme Greed)
  => desfavorable; entre medio => neutral.
- promedio_30_dias: mismo umbral, sobre el promedio del historial.
- tendencia: se reporta pero no puntúa (siempre neutral) - es
  información de momentum, no una señal direccional confiable por sí
  sola (un mercado puede pasar de miedo extremo a miedo moderado sin
  dejar de ser una zona de compra contrarian).
"""

from loguru import logger

from app.scoring.metric_types import puntaje_categoria
from app.sentiment.crypto_sentiment import calcular_sentimiento
from app.sentiment.fear_greed_provider import FearGreedProviderError

PUNTOS_TOTALES = 10

UMBRAL_MIEDO = 25
UMBRAL_CODICIA = 75

FUENTE = "Fear & Greed Index (alternative.me)"


def _senal_nivel(valor: float) -> str:
    if valor <= UMBRAL_MIEDO:
        return "favorable"
    if valor >= UMBRAL_CODICIA:
        return "desfavorable"
    return "neutral"


def calcular_score_sentimiento(provider=None) -> dict:
    """El Fear & Greed Index es de todo el mercado cripto - el resultado
    es el mismo para BTC y ETH."""
    logger.info("Calculando score de sentimiento...")

    try:
        s = calcular_sentimiento(provider)
    except FearGreedProviderError as e:
        logger.error(f"No se pudo calcular score de sentimiento: {e}")
        metricas = [
            {"metrica": "valor_actual", "valor": None, "unidad": None, "timestamp": None,
             "fuente": "no disponible", "senal": "sin_datos"},
            {"metrica": "promedio_30_dias", "valor": None, "unidad": None, "timestamp": None,
             "fuente": "no disponible", "senal": "sin_datos"},
            {"metrica": "tendencia", "valor": None, "unidad": None, "timestamp": None,
             "fuente": "no disponible", "senal": "sin_datos"},
        ]
        return puntaje_categoria(metricas, PUNTOS_TOTALES)

    metricas = [
        {"metrica": "valor_actual", "valor": s["valor_actual"], "unidad": "0-100",
         "timestamp": None, "fuente": FUENTE, "senal": _senal_nivel(s["valor_actual"])},
        {"metrica": "promedio_30_dias", "valor": s["valor_promedio"], "unidad": "0-100",
         "timestamp": None, "fuente": FUENTE, "senal": _senal_nivel(s["valor_promedio"])},
        {"metrica": "tendencia", "valor": s["tendencia"], "unidad": None,
         "timestamp": None, "fuente": FUENTE, "senal": "neutral"},
    ]

    resultado = puntaje_categoria(metricas, PUNTOS_TOTALES)
    logger.info(f"OK: score sentimiento = {resultado['puntos']}/{PUNTOS_TOTALES}")
    return resultado
