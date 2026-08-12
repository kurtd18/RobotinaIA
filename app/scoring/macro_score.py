"""
Score macro (10 puntos) del CryptoScoringEngine.

Reutiliza app/macro/crypto_macro.py (Fase 5). Reglas explícitas:
- DXY: dólar fuerte = contexto de risk-off, malo para cripto.
  tendencia "subiendo" => desfavorable; "bajando" => favorable; "estable" => neutral.
- US10Y: tasas subiendo = liquidez más cara, malo para activos de riesgo.
  Misma regla direccional que DXY.
- SP500: correlación positiva con cripto en entornos risk-on.
  tendencia "subiendo" => favorable; "bajando" => desfavorable; "estable" => neutral.
- GOLD: relación históricamente débil y ambigua con cripto (a veces
  correlacionado como cobertura, a veces inverso como refugio
  tradicional) - se reporta pero siempre neutral, no se fuerza una
  lectura direccional sin evidencia sólida.

El contexto macro es el mismo para BTC y ETH (no es específico de cripto).
"""

from loguru import logger

from app.macro.crypto_macro import calcular_contexto_macro
from app.macro.macro_provider import TICKERS_MACRO
from app.scoring.metric_types import puntaje_categoria

PUNTOS_TOTALES = 10

FUENTE = "Yahoo Finance (yfinance)"

POLARIDAD = {
    "DXY": "sube_desfavorable",
    "US10Y": "sube_desfavorable",
    "SP500": "sube_favorable",
    "GOLD": "neutral",
}


def _senal_por_tendencia(tendencia: str, polaridad: str) -> str:
    if polaridad == "neutral":
        return "neutral"
    if tendencia == "estable":
        return "neutral"
    if polaridad == "sube_favorable":
        return "favorable" if tendencia == "subiendo" else "desfavorable"
    return "desfavorable" if tendencia == "subiendo" else "favorable"


def calcular_score_macro(provider=None) -> dict:
    logger.info("Calculando score macro...")

    contexto = calcular_contexto_macro(provider)

    metricas = []
    for nombre in TICKERS_MACRO:
        if nombre in contexto:
            datos = contexto[nombre]
            metricas.append({
                "metrica": nombre, "valor": datos["valor_actual"], "unidad": datos["ticker"],
                "timestamp": None, "fuente": FUENTE,
                "senal": _senal_por_tendencia(datos["tendencia"], POLARIDAD[nombre]),
            })
        else:
            metricas.append({
                "metrica": nombre, "valor": None, "unidad": None, "timestamp": None,
                "fuente": "no disponible", "senal": "sin_datos",
            })

    resultado = puntaje_categoria(metricas, PUNTOS_TOTALES)
    logger.info(f"OK: score macro = {resultado['puntos']}/{PUNTOS_TOTALES}")
    return resultado
