"""
Pruebas del motor genérico de puntaje por categoría (metric_types.py).
No dependen de Internet.
"""

import pytest

from app.scoring.metric_types import puntaje_categoria


def _m(nombre, senal):
    return {"metrica": nombre, "valor": None, "unidad": None, "timestamp": None,
            "fuente": "test", "senal": senal}


def test_todas_favorables_da_puntaje_maximo():
    metricas = [_m("a", "favorable"), _m("b", "favorable")]

    resultado = puntaje_categoria(metricas, 30)

    assert resultado["puntos"] == pytest.approx(30.0)
    assert resultado["disponible"] is True
    assert resultado["cobertura"] == pytest.approx(1.0)


def test_todas_desfavorables_da_cero():
    metricas = [_m("a", "desfavorable"), _m("b", "desfavorable")]

    resultado = puntaje_categoria(metricas, 30)

    assert resultado["puntos"] == pytest.approx(0.0)


def test_mezcla_favorable_neutral_desfavorable():
    metricas = [_m("a", "favorable"), _m("b", "neutral"), _m("c", "desfavorable")]

    resultado = puntaje_categoria(metricas, 30)

    # promedio de valores (1.0 + 0.5 + 0.0) / 3 = 0.5 -> 15/30
    assert resultado["puntos"] == pytest.approx(15.0)


def test_sin_datos_no_penaliza_se_excluye_del_promedio():
    metricas = [_m("a", "favorable"), _m("b", "sin_datos")]

    resultado = puntaje_categoria(metricas, 30)

    # solo "a" cuenta -> favorable puro = 30
    assert resultado["puntos"] == pytest.approx(30.0)
    assert resultado["cobertura"] == pytest.approx(0.5)


def test_todas_sin_datos_queda_no_disponible():
    metricas = [_m("a", "sin_datos"), _m("b", "sin_datos")]

    resultado = puntaje_categoria(metricas, 30)

    assert resultado["puntos"] is None
    assert resultado["disponible"] is False
    assert resultado["cobertura"] == 0.0


def test_metricas_conservan_peso_y_puntos_individuales():
    metricas = [_m("a", "favorable"), _m("b", "favorable")]

    resultado = puntaje_categoria(metricas, 30)

    for m in resultado["metricas"]:
        assert m["peso"] == pytest.approx(0.5)
        assert m["puntos"] == pytest.approx(15.0)
