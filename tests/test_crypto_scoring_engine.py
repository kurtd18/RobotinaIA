"""
Pruebas de integración del CryptoScoringEngine (Fase 7). Todas las
subfunciones de score y la persistencia están mockeadas - no dependen
de Internet ni tocan robotinaia.db.
"""

import sqlite3
from unittest.mock import patch

import pytest

from app.scoring import repository
from app.scoring.crypto_scoring_engine import CryptoScoringEngine


@pytest.fixture(autouse=True)
def db_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "test_engine.db"

    def get_connection():
        return sqlite3.connect(ruta)

    monkeypatch.setattr(repository, "get_connection", get_connection)
    return ruta


def _cat(puntos, disponible=True, cobertura=1.0, metricas=None):
    return {"puntos": puntos, "disponible": disponible, "cobertura": cobertura,
            "metricas": metricas or []}


def _cat_tecnico(puntos, disponible=True):
    return {"puntos": puntos, "disponible": disponible, "cobertura": 1.0,
            "por_timeframe": {
                "4h": {"disponible": True, "puntos": 0.9, "metricas": []},
                "1h": {"disponible": True, "puntos": 0.9, "metricas": []},
                "15m": {"disponible": True, "puntos": 0.9, "metricas": []},
            } if disponible else {}}


def _patch_scores(fundamental=27.0, tecnico=27.0, derivados=18.0, sentimiento=9.0, macro=9.0,
                   riesgo_cumple=True, riesgo_disponible=True, riesgo_ratio=2.0):
    return patch.multiple(
        "app.scoring.crypto_scoring_engine",
        calcular_score_fundamental=lambda *a, **k: _cat(fundamental),
        calcular_score_tecnico=lambda *a, **k: _cat_tecnico(tecnico),
        calcular_score_derivados=lambda *a, **k: _cat(derivados),
        calcular_score_sentimiento=lambda *a, **k: _cat(sentimiento),
        calcular_score_macro=lambda *a, **k: _cat(macro),
        calcular_risk_reward=lambda *a, **k: {
            "disponible": riesgo_disponible, "ratio": riesgo_ratio, "cumple_minimo": riesgo_cumple,
            "entry": 100.0, "stop": 95.0, "target": 110.0,
            "distancia_stop": 5.0, "distancia_target": 10.0,
        },
    )


def test_score_alto_confidence_alta_y_riesgo_ok_da_long():
    # 27+27+18+9+9 = 90 -> score alto, todas las categorías con datos completos = alta confidence
    with _patch_scores(riesgo_cumple=True):
        engine = CryptoScoringEngine()
        resultado = engine.analizar("BTCUSDT")

    assert resultado["total_score"] == pytest.approx(90.0)
    assert resultado["signal"] == "LONG"
    assert resultado["signal_candidata"] == "LONG"


def test_score_bajo_confidence_alta_y_riesgo_ok_da_short():
    with _patch_scores(fundamental=1.0, tecnico=1.0, derivados=1.0, sentimiento=1.0, macro=1.0,
                        riesgo_cumple=True):
        engine = CryptoScoringEngine()
        resultado = engine.analizar("BTCUSDT")

    assert resultado["total_score"] == pytest.approx(5.0)
    assert resultado["signal"] == "SHORT"


def test_score_intermedio_da_no_operar():
    with _patch_scores(fundamental=15.0, tecnico=15.0, derivados=10.0, sentimiento=5.0, macro=5.0):
        engine = CryptoScoringEngine()
        resultado = engine.analizar("BTCUSDT")

    assert resultado["signal"] == "NO_OPERAR"


def test_riesgo_beneficio_insuficiente_fuerza_no_operar_aunque_score_sea_long():
    with _patch_scores(riesgo_cumple=False, riesgo_ratio=1.1):
        engine = CryptoScoringEngine()
        resultado = engine.analizar("BTCUSDT")

    assert resultado["signal_candidata"] == "LONG"
    assert resultado["signal"] == "NO_OPERAR"
    assert "riesgo/beneficio" in resultado["razones"][-1] or "riesgo/beneficio" in " ".join(resultado["razones"])


def test_riesgo_no_disponible_fuerza_no_operar_fail_safe():
    with _patch_scores(riesgo_disponible=False, riesgo_cumple=False, riesgo_ratio=None):
        engine = CryptoScoringEngine()
        resultado = engine.analizar("BTCUSDT")

    assert resultado["signal_candidata"] == "LONG"
    assert resultado["signal"] == "NO_OPERAR"


def test_no_operar_no_valida_riesgo_beneficio():
    with _patch_scores(fundamental=15.0, tecnico=15.0, derivados=10.0, sentimiento=5.0, macro=5.0) as _:
        with patch("app.scoring.crypto_scoring_engine.calcular_risk_reward") as mock_riesgo:
            engine = CryptoScoringEngine()
            resultado = engine.analizar("BTCUSDT")

    mock_riesgo.assert_not_called()
    assert resultado["signal"] == "NO_OPERAR"
    assert resultado["risk_reward"] is None


def test_categoria_totalmente_sin_datos_usa_valor_neutral_no_cero():
    with _patch_scores() as _:
        with patch("app.scoring.crypto_scoring_engine.calcular_score_macro",
                    return_value=_cat(None, disponible=False, cobertura=0.0)):
            engine = CryptoScoringEngine()
            resultado = engine.analizar("BTCUSDT")

    assert resultado["score_macro"] == pytest.approx(5.0)  # 10 * 0.5, no penaliza a 0


def test_deteccion_cambio_de_senal():
    with _patch_scores(riesgo_cumple=True):
        engine = CryptoScoringEngine()
        primer_resultado = engine.analizar("BTCUSDT")

    assert primer_resultado["cambio_senal"] is None  # no había historial previo

    with _patch_scores(fundamental=15.0, tecnico=15.0, derivados=10.0, sentimiento=5.0, macro=5.0):
        segundo_resultado = engine.analizar("BTCUSDT")

    assert segundo_resultado["cambio_senal"] == {"de": "LONG", "a": "NO_OPERAR"}


def test_simbolo_no_soportado():
    engine = CryptoScoringEngine()
    with pytest.raises(ValueError):
        engine.analizar("FAKEUSDT")


def test_persistir_false_no_guarda_en_bd():
    with _patch_scores():
        engine = CryptoScoringEngine()
        resultado = engine.analizar("BTCUSDT", persistir=False)

    assert "id" not in resultado
    assert repository.obtener_ultima_senal("BTCUSDT") is None
