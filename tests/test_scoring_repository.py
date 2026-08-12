"""
Pruebas de persistencia del CryptoScoringEngine (Fase 7). Usa un archivo
SQLite temporal real (no la base de datos del proyecto) - no depende de
Internet ni toca robotinaia.db.
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from app.scoring import repository


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "test_crypto_scores.db"

    def get_connection():
        return sqlite3.connect(ruta)

    monkeypatch.setattr(repository, "get_connection", get_connection)
    return ruta


def _resultado(symbol="BTCUSDT", signal="LONG", total_score=80.0, confidence=75.0):
    return {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc),
        "score_fundamental": 25.0, "score_tecnico": 25.0, "score_derivados": 15.0,
        "score_sentimiento": 8.0, "score_macro": 7.0,
        "total_score": total_score, "confidence": confidence, "signal": signal,
        "risk_reward": {"ratio": 2.0, "disponible": True},
        "razones": ["test"],
    }


def test_guardar_resultado_devuelve_id(db_temporal):
    id_guardado = repository.guardar_resultado(_resultado())

    assert isinstance(id_guardado, int)
    assert id_guardado > 0


def test_obtener_ultima_senal_sin_historial_es_none(db_temporal):
    assert repository.obtener_ultima_senal("BTCUSDT") is None


def test_obtener_ultima_senal_devuelve_el_mas_reciente(db_temporal):
    repository.guardar_resultado(_resultado(signal="NO_OPERAR", total_score=50.0))
    repository.guardar_resultado(_resultado(signal="LONG", total_score=80.0))

    ultima = repository.obtener_ultima_senal("BTCUSDT")

    assert ultima["signal"] == "LONG"
    assert ultima["total_score"] == pytest.approx(80.0)


def test_obtener_ultima_senal_filtra_por_symbol(db_temporal):
    repository.guardar_resultado(_resultado(symbol="BTCUSDT", signal="LONG"))
    repository.guardar_resultado(_resultado(symbol="ETHUSDT", signal="SHORT"))

    btc = repository.obtener_ultima_senal("BTCUSDT")
    eth = repository.obtener_ultima_senal("ETHUSDT")

    assert btc["signal"] == "LONG"
    assert eth["signal"] == "SHORT"


def test_detalle_json_se_guarda_completo(db_temporal):
    repository.guardar_resultado(_resultado())

    conn = repository.get_connection()
    fila = conn.execute("SELECT detalle_json FROM crypto_scores").fetchone()
    conn.close()

    assert '"signal": "LONG"' in fila[0]
