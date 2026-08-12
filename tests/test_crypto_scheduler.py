"""
Pruebas del scheduler crypto (Fase 10). Todo mockeado (run_crypto_analysis
y la persistencia de idempotencia usan un SQLite temporal) - no
dependen de Internet.
"""

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.scheduler import crypto_scheduler, repository
from app.scoring.crypto_scoring_engine import SIMBOLOS_SOPORTADOS

N_SIMBOLOS = len(SIMBOLOS_SOPORTADOS)


@pytest.fixture(autouse=True)
def db_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "test_scheduler.db"

    def get_connection():
        return sqlite3.connect(ruta)

    monkeypatch.setattr(repository, "get_connection", get_connection)
    return ruta


@pytest.fixture(autouse=True)
def mock_notificaciones():
    """
    Las notificaciones de Telegram ahora las dispara el propio scheduler
    (resumen global + detalle por moneda) - se mockean por defecto en
    todos los tests para no depender de Internet ni de tokens reales.
    """
    with patch("app.scheduler.crypto_scheduler.notificar") as mock_notificar, \
         patch("app.scheduler.crypto_scheduler.notificar_resumen_global") as mock_resumen_global:
        mock_notificar.return_value = ["mensaje detalle"]
        mock_resumen_global.return_value = "mensaje resumen global"
        yield {"notificar": mock_notificar, "notificar_resumen_global": mock_resumen_global}


def _pipeline_ok(symbol, **kwargs):
    return {
        "symbol": symbol,
        "resultado": {"signal": "NO_OPERAR", "total_score": 50.0, "confidence": 60.0,
                      "metricas_sin_datos": [], "score_fundamental": 15.0, "score_tecnico": 15.0,
                      "score_derivados": 10.0, "score_sentimiento": 5.0, "score_macro": 5.0,
                      "cambio_senal": None, "razones": []},
        "paper_resultado": {"posiciones_cerradas": [], "posicion_abierta": None},
        "telegram_enviados": [],
    }


# ---------- conversión de timezone ----------

def test_hora_colombia_actual_usa_zona_america_bogota():
    ahora = crypto_scheduler.hora_colombia_actual()
    assert ahora.tzinfo is not None
    assert str(ahora.tzinfo) in (str(ZoneInfo("America/Bogota")),) or ahora.tzinfo.key == "America/Bogota"


def test_conversion_correcta_independiente_de_timezone_del_servidor():
    # 11:00 UTC = 06:00 Colombia (Bogotá es UTC-5 todo el año, sin horario de verano)
    en_utc = datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc)

    assert crypto_scheduler.debe_ejecutar_ahora(en_utc) == "06:00"


def test_conversion_desde_otra_timezone_no_america_bogota():
    # Bogotá es UTC-5 fijo; Tokio es UTC+9 fijo -> 14h de diferencia.
    # 10:00 Colombia el 12/08 = 15:00 UTC el 12/08 = 00:00 Tokio el 13/08.
    en_tokio = datetime(2026, 8, 13, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert crypto_scheduler.debe_ejecutar_ahora(en_tokio) == "10:00"


# ---------- corre cada hora en punto ----------

@pytest.mark.parametrize("hora,esperado", [
    (0, "00:00"), (6, "06:00"), (10, "10:00"), (12, "12:00"),
    (14, "14:00"), (18, "18:00"), (23, "23:00"),
])
def test_cada_hora_en_punto_dispara(hora, esperado):
    ahora = datetime(2026, 8, 12, hora, 0, tzinfo=ZoneInfo("America/Bogota"))
    assert crypto_scheduler.debe_ejecutar_ahora(ahora) == esperado


@pytest.mark.parametrize("hora,minuto", [(6, 1), (9, 59), (12, 30), (23, 45)])
def test_fuera_del_minuto_00_no_dispara(hora, minuto):
    ahora = datetime(2026, 8, 12, hora, minuto, tzinfo=ZoneInfo("America/Bogota"))
    assert crypto_scheduler.debe_ejecutar_ahora(ahora) is None


# ---------- ejecución del pipeline ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_ejecutar_analisis_programado_corre_btc_y_eth(mock_run):
    mock_run.side_effect = _pipeline_ok

    resultado = crypto_scheduler.ejecutar_analisis_programado()

    assert set(resultado["resultados"].keys()) == set(SIMBOLOS_SOPORTADOS)
    assert mock_run.call_count == N_SIMBOLOS
    assert resultado["errores"] == []


# ---------- error de BTC no detiene ETH y viceversa ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_error_btc_no_detiene_eth(mock_run):
    def run(symbol, **kwargs):
        if symbol == "BTCUSDT":
            raise RuntimeError("Binance caído")
        return _pipeline_ok(symbol)

    mock_run.side_effect = run

    resultado = crypto_scheduler.ejecutar_analisis_programado()

    assert resultado["resultados"]["BTCUSDT"] is None
    assert resultado["resultados"]["ETHUSDT"] is not None
    assert len(resultado["errores"]) == 1
    assert "BTCUSDT" in resultado["errores"][0]


@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_error_eth_no_detiene_btc(mock_run):
    def run(symbol, **kwargs):
        if symbol == "ETHUSDT":
            raise RuntimeError("Binance caído")
        return _pipeline_ok(symbol)

    mock_run.side_effect = run

    resultado = crypto_scheduler.ejecutar_analisis_programado()

    assert resultado["resultados"]["ETHUSDT"] is None
    assert resultado["resultados"]["BTCUSDT"] is not None
    assert len(resultado["errores"]) == 1


# ---------- error de Telegram no detiene el scheduler ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_error_telegram_resumen_global_no_detiene_scheduler(mock_run, mock_notificaciones):
    mock_run.side_effect = _pipeline_ok
    mock_notificaciones["notificar_resumen_global"].side_effect = RuntimeError("Telegram caído")

    resultado = crypto_scheduler.ejecutar_analisis_programado()

    assert resultado["errores"] == []  # el fallo de Telegram no cuenta como error del scheduler
    assert set(resultado["resultados"].keys()) == set(SIMBOLOS_SOPORTADOS)
    # a pesar del resumen global fallido, el detalle por moneda se sigue mandando
    assert mock_notificaciones["notificar"].call_count == N_SIMBOLOS


@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_error_telegram_detalle_de_un_activo_no_detiene_los_demas(mock_run, mock_notificaciones):
    mock_run.side_effect = _pipeline_ok

    def notificar_side_effect(symbol, resultado, paper_resultado):
        if symbol == "BTCUSDT":
            raise RuntimeError("Telegram caído")
        return ["mensaje"]

    mock_notificaciones["notificar"].side_effect = notificar_side_effect

    resultado = crypto_scheduler.ejecutar_analisis_programado()

    assert resultado["errores"] == []
    assert mock_notificaciones["notificar"].call_count == N_SIMBOLOS


# ---------- orden: resumen global primero, detalle por moneda después ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_resumen_global_se_envia_antes_que_el_detalle_por_moneda(mock_run, mock_notificaciones):
    mock_run.side_effect = _pipeline_ok
    orden = []
    mock_notificaciones["notificar_resumen_global"].side_effect = lambda *a, **k: orden.append("resumen_global")
    mock_notificaciones["notificar"].side_effect = lambda *a, **k: orden.append("detalle") or ["m"]

    crypto_scheduler.ejecutar_analisis_programado()

    assert orden[0] == "resumen_global"
    assert orden[1:] == ["detalle"] * N_SIMBOLOS


@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_resumen_global_recibe_el_resultado_de_todos_los_activos(mock_run, mock_notificaciones):
    mock_run.side_effect = _pipeline_ok

    crypto_scheduler.ejecutar_analisis_programado()

    resultados_pasados = mock_notificaciones["notificar_resumen_global"].call_args[0][0]
    assert set(resultados_pasados.keys()) == set(SIMBOLOS_SOPORTADOS)


@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_resumen_global_incluye_none_para_activo_que_fallo(mock_run, mock_notificaciones):
    def run(symbol, **kwargs):
        if symbol == "BTCUSDT":
            raise RuntimeError("Binance caído")
        return _pipeline_ok(symbol)

    mock_run.side_effect = run

    crypto_scheduler.ejecutar_analisis_programado()

    resultados_pasados = mock_notificaciones["notificar_resumen_global"].call_args[0][0]
    assert resultados_pasados["BTCUSDT"] is None


# ---------- ejecución duplicada (idempotencia) ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_ejecucion_duplicada_no_vuelve_a_correr_el_pipeline(mock_run):
    mock_run.side_effect = _pipeline_ok
    ahora = datetime(2026, 8, 12, 6, 0, tzinfo=ZoneInfo("America/Bogota"))

    primera = crypto_scheduler.ejecutar_ciclo_programado("06:00", ahora)
    segunda = crypto_scheduler.ejecutar_ciclo_programado("06:00", ahora)

    assert primera is not None
    assert segunda is None  # se saltó por idempotencia
    assert mock_run.call_count == N_SIMBOLOS  # solo la primera corrida, no el doble


@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_ventanas_distintas_si_ejecutan_ambas(mock_run):
    mock_run.side_effect = _pipeline_ok
    ahora_06 = datetime(2026, 8, 12, 6, 0, tzinfo=ZoneInfo("America/Bogota"))
    ahora_10 = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("America/Bogota"))

    r1 = crypto_scheduler.ejecutar_ciclo_programado("06:00", ahora_06)
    r2 = crypto_scheduler.ejecutar_ciclo_programado("10:00", ahora_10)

    assert r1 is not None
    assert r2 is not None
    assert mock_run.call_count == N_SIMBOLOS * 2


# ---------- persistencia (se propaga a run_crypto_analysis con persistir por defecto) ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_scheduler_no_desactiva_la_persistencia(mock_run):
    mock_run.side_effect = _pipeline_ok

    crypto_scheduler.ejecutar_analisis_programado()

    for llamada in mock_run.call_args_list:
        # no se pasa persistir=False explícitamente - se deja el default (True) de run_crypto_analysis
        assert "persistir" not in llamada.kwargs or llamada.kwargs["persistir"] is True


# ---------- cambio de señal y paper trading (se propagan, no se recalculan) ----------

@patch("app.scheduler.crypto_scheduler.run_crypto_analysis")
def test_resumen_incluye_datos_de_paper_trading_y_senal(mock_run):
    def run(symbol, **kwargs):
        r = _pipeline_ok(symbol)
        r["resultado"]["signal"] = "LONG"
        r["resultado"]["cambio_senal"] = {"de": "NO_OPERAR", "a": "LONG"}
        r["paper_resultado"]["posicion_abierta"] = {"direction": "LONG"}
        return r

    mock_run.side_effect = run

    resultado = crypto_scheduler.ejecutar_analisis_programado()

    assert resultado["resultados"]["BTCUSDT"]["resultado"]["cambio_senal"] == {"de": "NO_OPERAR", "a": "LONG"}
    assert resultado["resultados"]["BTCUSDT"]["paper_resultado"]["posicion_abierta"] is not None
