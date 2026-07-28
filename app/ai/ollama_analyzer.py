"""
Motor de análisis de IA para RobotinaIA, usando un modelo local vía Ollama.
"""

from loguru import logger
from ollama import chat
import yfinance as yf

OLLAMA_MODEL = "llama3.1"


class AnalisisNoDisponible(Exception):
    """Se lanza cuando no se puede generar el análisis (sin datos de mercado u Ollama no responde)."""


def _obtener_datos_mercado(symbol):
    info = yf.Ticker(symbol).info

    precio = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    variacion = info.get("regularMarketChangePercent")
    maximo = info.get("dayHigh")
    minimo = info.get("dayLow")

    if precio is None:
        raise AnalisisNoDisponible(f"No hay datos de precio disponibles para {symbol}")

    return precio, variacion, maximo, minimo


def _construir_prompt(symbol, precio, variacion, maximo, minimo):
    variacion_str = f"{variacion:.2f}%" if variacion is not None else "N/D"

    return f"""
Actua como RobotinaIA.

Analiza la siguiente informacion:

- Activo: {symbol}
- Precio actual: {precio}
- Variacion diaria: {variacion_str}
- Maximo del dia: {maximo}
- Minimo del dia: {minimo}

Entrega:
1. Resumen ejecutivo.
2. Nivel de riesgo (Bajo, Medio o Alto).
3. Recomendacion (Comprar, Mantener o Vender).
"""


def analizar_activo(symbol):
    """Genera un análisis de IA para el activo dado.

    Lanza AnalisisNoDisponible si no hay datos de mercado o si Ollama no responde.
    """

    try:
        precio, variacion, maximo, minimo = _obtener_datos_mercado(symbol)
    except AnalisisNoDisponible:
        raise
    except Exception as e:
        logger.exception(f"Error obteniendo datos de mercado para {symbol}")
        raise AnalisisNoDisponible(
            f"No se pudo obtener información de mercado para {symbol}"
        ) from e

    prompt = _construir_prompt(symbol, precio, variacion, maximo, minimo)

    try:
        response = chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}])
    except Exception as e:
        logger.exception(f"Error generando análisis con Ollama para {symbol}")
        raise AnalisisNoDisponible(
            "El motor de análisis de IA no está disponible en este momento"
        ) from e

    return response["message"]["content"]