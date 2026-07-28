"""
Pruebas del clasificador de recomendación (AlertEngine).
"""

from app.services.alert_engine import AlertEngine
from app.core.settings import Settings


def test_score_bajo_no_comprar():
    engine = AlertEngine()
    assert engine.get_recommendation(30) == "NO COMPRAR"


def test_score_medio_revisar():
    engine = AlertEngine()
    assert engine.get_recommendation(65) == "REVISAR"


def test_score_alto_oportunidad():
    engine = AlertEngine()
    assert engine.get_recommendation(95) == "OPORTUNIDAD"


def test_umbral_exacto_es_oportunidad():
    """El umbral configurado (Settings.UMBRAL_SENAL) debe clasificar como OPORTUNIDAD."""
    engine = AlertEngine()
    assert engine.get_recommendation(Settings.UMBRAL_SENAL) == "OPORTUNIDAD"


def test_justo_debajo_del_umbral_es_revisar():
    engine = AlertEngine()
    assert engine.get_recommendation(Settings.UMBRAL_SENAL - 1) == "REVISAR"