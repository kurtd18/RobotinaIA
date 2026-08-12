"""
Pruebas del cálculo de confidence (Fase 7). No dependen de Internet.
"""

import pytest

from app.scoring.confidence import calcular_confidence

PUNTOS_TOTALES = {"fundamental": 30, "tecnico": 30, "derivados": 20, "sentimiento": 10, "macro": 10}


def _metrica(senal, fuente="Binance Klines API"):
    return {"metrica": "x", "senal": senal, "fuente": fuente}


def _categoria(puntos, maximo, cobertura=1.0, metricas=None):
    return {
        "puntos": puntos, "disponible": puntos is not None, "cobertura": cobertura,
        "metricas": metricas or [_metrica("favorable")],
    }


def test_todo_disponible_y_de_acuerdo_da_confidence_alta():
    categorias = {
        "fundamental": _categoria(28, 30, metricas=[_metrica("favorable", "Blockchain.com Charts API")]),
        "tecnico": {"puntos": 27, "disponible": True, "cobertura": 1.0,
                    "por_timeframe": {
                        "4h": {"disponible": True, "puntos": 0.9, "metricas": [_metrica("favorable", "Binance Klines API")]},
                        "1h": {"disponible": True, "puntos": 0.9, "metricas": [_metrica("favorable", "Binance Klines API")]},
                        "15m": {"disponible": True, "puntos": 0.9, "metricas": [_metrica("favorable", "Binance Klines API")]},
                    }},
        "derivados": _categoria(18, 20, metricas=[_metrica("favorable", "Binance Futures API")]),
        "sentimiento": _categoria(9, 10, metricas=[_metrica("favorable", "Fear & Greed Index")]),
        "macro": _categoria(9, 10, metricas=[_metrica("favorable", "Yahoo Finance")]),
    }

    resultado = calcular_confidence(categorias, PUNTOS_TOTALES)

    assert resultado["confidence"] > 80


def test_todo_sin_datos_da_confidence_cero():
    categorias = {
        "fundamental": {"puntos": None, "disponible": False, "cobertura": 0.0, "metricas": []},
        "tecnico": {"puntos": None, "disponible": False, "cobertura": 0.0, "por_timeframe": {}},
        "derivados": {"puntos": None, "disponible": False, "cobertura": 0.0, "metricas": []},
        "sentimiento": {"puntos": None, "disponible": False, "cobertura": 0.0, "metricas": []},
        "macro": {"puntos": None, "disponible": False, "cobertura": 0.0, "metricas": []},
    }

    resultado = calcular_confidence(categorias, PUNTOS_TOTALES)

    assert resultado["confidence"] < 30  # cobertura/fuentes/acuerdo caen a 0, temporalidades queda neutral (50)


def test_desacuerdo_entre_categorias_reduce_confidence_vs_acuerdo():
    categorias_acuerdo = {
        "fundamental": _categoria(28, 30),
        "tecnico": {"puntos": 27, "disponible": True, "cobertura": 1.0, "por_timeframe": {}},
        "derivados": _categoria(18, 20),
        "sentimiento": _categoria(9, 10),
        "macro": _categoria(9, 10),
    }
    categorias_desacuerdo = {
        "fundamental": _categoria(28, 30),      # alcista
        "tecnico": {"puntos": 2, "disponible": True, "cobertura": 1.0, "por_timeframe": {}},  # bajista
        "derivados": _categoria(18, 20),        # alcista
        "sentimiento": _categoria(1, 10),       # bajista
        "macro": _categoria(9, 10),             # alcista
    }

    r_acuerdo = calcular_confidence(categorias_acuerdo, PUNTOS_TOTALES)
    r_desacuerdo = calcular_confidence(categorias_desacuerdo, PUNTOS_TOTALES)

    assert r_acuerdo["confidence"] > r_desacuerdo["confidence"]


def test_factores_incluye_las_cuatro_claves():
    categorias = {
        "fundamental": _categoria(28, 30),
        "tecnico": {"puntos": 27, "disponible": True, "cobertura": 1.0, "por_timeframe": {}},
        "derivados": _categoria(18, 20),
        "sentimiento": _categoria(9, 10),
        "macro": _categoria(9, 10),
    }

    resultado = calcular_confidence(categorias, PUNTOS_TOTALES)

    assert set(resultado["factores"].keys()) == {
        "cobertura_datos", "calidad_fuentes", "acuerdo_temporalidades", "acuerdo_categorias"
    }
