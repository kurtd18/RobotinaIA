"""
Pruebas del PaperTradingEngine y su repositorio (Fase 8). Usa un
archivo SQLite temporal real (no robotinaia.db) y un BinanceProvider
mockeado - no dependen de Internet ni ejecutan ninguna operación real.
"""

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.paper_trading import repository
from app.paper_trading.paper_trading_engine import PaperTradingEngine
from app.providers.binance_provider import BinanceProviderError


@pytest.fixture(autouse=True)
def db_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "test_paper_trading.db"

    def get_connection():
        return sqlite3.connect(ruta)

    monkeypatch.setattr(repository, "get_connection", get_connection)
    return ruta


def _mock_provider(precio_actual=100.0):
    provider = MagicMock()
    idx = pd.date_range("2026-01-01", periods=1, freq="1h", tz="UTC")
    df = pd.DataFrame({"Open": [precio_actual], "High": [precio_actual], "Low": [precio_actual],
                        "Close": [precio_actual], "Volume": [1.0]}, index=idx)
    provider.get_ohlcv.return_value = df
    return provider


def _resultado_long(entry=100.0, stop=95.0, target=110.0):
    return {"signal": "LONG", "id": 1,
            "risk_reward": {"disponible": True, "entry": entry, "stop": stop, "target": target,
                             "ratio": 2.0, "cumple_minimo": True}}


def _resultado_short(entry=100.0, stop=105.0, target=90.0):
    return {"signal": "SHORT", "id": 1,
            "risk_reward": {"disponible": True, "entry": entry, "stop": stop, "target": target,
                             "ratio": 2.0, "cumple_minimo": True}}


def _resultado_no_operar():
    return {"signal": "NO_OPERAR", "id": 1, "risk_reward": None}


# ---------- abrir_posicion ----------

def test_abrir_posicion_long_calcula_cantidad_correcta():
    engine = PaperTradingEngine(provider=_mock_provider(), capital_por_posicion=1000.0)

    pos = engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long(entry=100.0))

    assert pos is not None
    assert pos["quantity"] == pytest.approx(10.0)  # 1000 / 100
    assert pos["size_usdt"] == pytest.approx(1000.0)


def test_no_abre_segunda_posicion_si_ya_hay_una_abierta():
    engine = PaperTradingEngine(provider=_mock_provider())
    engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long())

    segunda = engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long())

    assert segunda is None
    assert len(repository.obtener_posiciones_abiertas("BTCUSDT")) == 1


def test_no_abre_si_risk_reward_no_disponible():
    engine = PaperTradingEngine(provider=_mock_provider())
    resultado = {"signal": "LONG", "id": 1, "risk_reward": {"disponible": False}}

    pos = engine.abrir_posicion("BTCUSDT", "LONG", resultado)

    assert pos is None


# ---------- revisar_posiciones_abiertas ----------

def test_long_se_cierra_por_stop():
    engine = PaperTradingEngine(provider=_mock_provider())
    engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long(entry=100.0, stop=95.0, target=110.0))

    cerradas = engine.revisar_posiciones_abiertas("BTCUSDT", precio_actual=94.0)

    assert len(cerradas) == 1
    assert cerradas[0]["close_reason"] == "STOP"
    assert cerradas[0]["pnl_usdt"] < 0


def test_long_se_cierra_por_target():
    engine = PaperTradingEngine(provider=_mock_provider())
    engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long(entry=100.0, stop=95.0, target=110.0))

    cerradas = engine.revisar_posiciones_abiertas("BTCUSDT", precio_actual=111.0)

    assert cerradas[0]["close_reason"] == "TARGET"
    assert cerradas[0]["pnl_usdt"] > 0


def test_long_no_se_cierra_dentro_del_rango():
    engine = PaperTradingEngine(provider=_mock_provider())
    engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long(entry=100.0, stop=95.0, target=110.0))

    cerradas = engine.revisar_posiciones_abiertas("BTCUSDT", precio_actual=102.0)

    assert cerradas == []
    assert len(repository.obtener_posiciones_abiertas("BTCUSDT")) == 1


def test_short_se_cierra_por_stop_cuando_precio_sube():
    engine = PaperTradingEngine(provider=_mock_provider())
    engine.abrir_posicion("BTCUSDT", "SHORT", _resultado_short(entry=100.0, stop=105.0, target=90.0))

    cerradas = engine.revisar_posiciones_abiertas("BTCUSDT", precio_actual=106.0)

    assert cerradas[0]["close_reason"] == "STOP"
    assert cerradas[0]["pnl_usdt"] < 0


def test_short_se_cierra_por_target_cuando_precio_baja():
    engine = PaperTradingEngine(provider=_mock_provider())
    engine.abrir_posicion("BTCUSDT", "SHORT", _resultado_short(entry=100.0, stop=105.0, target=90.0))

    cerradas = engine.revisar_posiciones_abiertas("BTCUSDT", precio_actual=89.0)

    assert cerradas[0]["close_reason"] == "TARGET"
    assert cerradas[0]["pnl_usdt"] > 0


def test_pnl_calculado_correctamente_long_ganador():
    engine = PaperTradingEngine(provider=_mock_provider(), capital_por_posicion=1000.0)
    engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long(entry=100.0, stop=95.0, target=110.0))

    cerradas = engine.revisar_posiciones_abiertas("BTCUSDT", precio_actual=110.0)

    # quantity = 10, ganancia = (110-100)*10 = 100 USDT = 10% de 1000
    assert cerradas[0]["pnl_usdt"] == pytest.approx(100.0)
    assert cerradas[0]["pnl_pct"] == pytest.approx(10.0)


# ---------- procesar (integración) ----------

def test_procesar_no_operar_no_abre_posicion():
    engine = PaperTradingEngine(provider=_mock_provider(100.0))

    resultado = engine.procesar("BTCUSDT", _resultado_no_operar())

    assert resultado["posicion_abierta"] is None
    assert repository.obtener_posiciones_abiertas("BTCUSDT") == []


def test_procesar_long_abre_posicion():
    engine = PaperTradingEngine(provider=_mock_provider(100.0))

    resultado = engine.procesar("BTCUSDT", _resultado_long(entry=100.0))

    assert resultado["posicion_abierta"] is not None
    assert len(repository.obtener_posiciones_abiertas("BTCUSDT")) == 1


def test_procesar_revisa_y_cierra_antes_de_intentar_abrir():
    engine = PaperTradingEngine(provider=_mock_provider(111.0))
    engine.abrir_posicion("BTCUSDT", "LONG", _resultado_long(entry=100.0, stop=95.0, target=110.0))

    resultado = engine.procesar("BTCUSDT", _resultado_no_operar())

    assert len(resultado["posiciones_cerradas"]) == 1
    assert resultado["posiciones_cerradas"][0]["close_reason"] == "TARGET"


def test_procesar_provider_falla_no_rompe(monkeypatch):
    provider = MagicMock()
    provider.get_ohlcv.side_effect = BinanceProviderError("sin datos")
    engine = PaperTradingEngine(provider=provider)

    resultado = engine.procesar("BTCUSDT", _resultado_long())

    assert "error" in resultado
    assert resultado["posicion_abierta"] is None


# ---------- repository ----------

def test_repository_guardar_y_obtener_abiertas():
    posicion = {
        "symbol": "ETHUSDT", "direction": "LONG", "entry_price": 2000.0,
        "stop_price": 1900.0, "target_price": 2200.0, "size_usdt": 1000.0,
        "quantity": 0.5, "opened_at": datetime.now(timezone.utc), "scoring_id": None,
    }
    repository.guardar_posicion_abierta(posicion)

    abiertas = repository.obtener_posiciones_abiertas("ETHUSDT")

    assert len(abiertas) == 1
    assert abiertas[0]["direction"] == "LONG"


def test_repository_cerrar_posicion_actualiza_estado():
    posicion = {
        "symbol": "ETHUSDT", "direction": "LONG", "entry_price": 2000.0,
        "stop_price": 1900.0, "target_price": 2200.0, "size_usdt": 1000.0,
        "quantity": 0.5, "opened_at": datetime.now(timezone.utc), "scoring_id": None,
    }
    id_pos = repository.guardar_posicion_abierta(posicion)

    repository.cerrar_posicion(id_pos, 2200.0, "TARGET", 100.0, 10.0, datetime.now(timezone.utc))

    assert repository.obtener_posiciones_abiertas("ETHUSDT") == []
    historial = repository.obtener_historial("ETHUSDT")
    assert historial[0]["status"] == "CLOSED"
    assert historial[0]["pnl_usdt"] == pytest.approx(100.0)


def test_repository_historial_sin_filtro_devuelve_todos():
    for symbol in ("BTCUSDT", "ETHUSDT"):
        repository.guardar_posicion_abierta({
            "symbol": symbol, "direction": "LONG", "entry_price": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "size_usdt": 1000.0,
            "quantity": 10.0, "opened_at": datetime.now(timezone.utc), "scoring_id": None,
        })

    historial = repository.obtener_historial()

    assert len(historial) == 2
