"""
Pruebas de las notificaciones de Telegram para cripto (Fase 9). El
envío real (enviar_mensaje_telegram) está mockeado - no dependen de
Internet ni mandan mensajes reales.
"""

from unittest.mock import MagicMock, patch

from app.notifications.crypto_telegram import notificar, notificar_resumen_global
from app.notifications.crypto_telegram_commands import cripto_command


def _resultado(cambio_senal=None, total_score=50.0, confidence=60.0, signal="NO_OPERAR"):
    return {
        "symbol": "BTCUSDT", "total_score": total_score, "confidence": confidence,
        "signal": signal, "cambio_senal": cambio_senal, "razones": ["motivo de prueba"],
        "score_fundamental": 15.0, "score_tecnico": 15.0, "score_derivados": 10.0,
        "score_sentimiento": 5.0, "score_macro": 5.0, "metricas_sin_datos": [],
    }


# ---------- notificar (solo activos operables) ----------

@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_no_operar_no_envia_mensaje_detallado(mock_enviar):
    enviados = notificar("BTCUSDT", _resultado(signal="NO_OPERAR"))

    mock_enviar.assert_not_called()
    assert enviados == []


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_long_envia_mensaje_detallado(mock_enviar):
    enviados = notificar("BTCUSDT", _resultado(signal="LONG"))

    mock_enviar.assert_called_once()
    assert len(enviados) == 1


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_short_envia_mensaje_detallado(mock_enviar):
    enviados = notificar("BTCUSDT", _resultado(signal="SHORT"))

    mock_enviar.assert_called_once()


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_detalle_incluye_desglose_por_categoria(mock_enviar):
    enviados = notificar("BTCUSDT", _resultado(signal="LONG"))

    assert "Fundamental: 15.0/30" in enviados[0]
    assert "Técnico: 15.0/30" in enviados[0]


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_cambio_de_senal_se_refleja_en_el_detalle(mock_enviar):
    resultado = _resultado(signal="LONG", cambio_senal={"de": "NO_OPERAR", "a": "LONG"})

    enviados = notificar("BTCUSDT", resultado)

    assert "NO_OPERAR -> LONG" in enviados[0]


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_posicion_cerrada_se_notifica_aunque_la_senal_actual_sea_no_operar(mock_enviar):
    # la posición se abrió cuando la señal era operable; que ahora cierre
    # con NO_OPERAR no debe silenciar el evento de cierre
    paper_resultado = {"posiciones_cerradas": [
        {"direction": "LONG", "entry_price": 100.0, "close_price": 110.0,
         "close_reason": "TARGET", "pnl_usdt": 100.0, "pnl_pct": 10.0}
    ], "posicion_abierta": None}

    enviados = notificar("BTCUSDT", _resultado(signal="NO_OPERAR"), paper_resultado)

    assert mock_enviar.call_count == 1  # solo el cierre, sin detalle (no operable)
    assert "CERRADA" in enviados[0]


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_posicion_abierta_envia_mensaje_adicional_junto_al_detalle(mock_enviar):
    paper_resultado = {"posiciones_cerradas": [], "posicion_abierta": {
        "direction": "LONG", "entry_price": 100.0, "stop_price": 95.0,
        "target_price": 110.0, "size_usdt": 1000.0,
    }}

    enviados = notificar("BTCUSDT", _resultado(signal="LONG"), paper_resultado)

    assert mock_enviar.call_count == 2  # detalle + apertura
    assert "ABIERTA" in enviados[1]


# ---------- notificar_resumen_global ----------

@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_resumen_global_incluye_todos_los_activos(mock_enviar):
    resultados = {
        "BTCUSDT": _resultado(signal="LONG", total_score=80.0, confidence=75.0),
        "ETHUSDT": _resultado(signal="NO_OPERAR", total_score=50.0, confidence=60.0),
    }

    mensaje = notificar_resumen_global(resultados)

    mock_enviar.assert_called_once()
    assert "BTC" in mensaje
    assert "ETH" in mensaje


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_resumen_global_usa_html(mock_enviar):
    notificar_resumen_global({"BTCUSDT": _resultado()})

    mock_enviar.assert_called_once()
    assert mock_enviar.call_args.kwargs.get("parse_mode") == "HTML"


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_resumen_global_marca_los_activos_a_operar(mock_enviar):
    resultados = {
        "BTCUSDT": _resultado(signal="LONG"),
        "ETHUSDT": _resultado(signal="NO_OPERAR"),
    }

    mensaje = notificar_resumen_global(resultados)

    assert "A operar:" in mensaje
    assert "BTC (LONG)" in mensaje
    assert "ETH (LONG)" not in mensaje


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_resumen_global_sin_activos_operables_lo_indica(mock_enviar):
    mensaje = notificar_resumen_global({"BTCUSDT": _resultado(signal="NO_OPERAR")})

    assert "Ningún activo cumple los criterios" in mensaje


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_resumen_global_marca_error_para_activo_fallido(mock_enviar):
    mensaje = notificar_resumen_global({"BTCUSDT": None, "ETHUSDT": _resultado()})

    assert "ERROR" in mensaje


@patch("app.notifications.crypto_telegram.enviar_mensaje_telegram")
def test_resumen_global_envia_un_solo_mensaje(mock_enviar):
    notificar_resumen_global({s: _resultado() for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")})

    assert mock_enviar.call_count == 1


# ---------- cripto_command ----------

def _mock_resultado_engine(symbol, total_score=80.0, confidence=75.0, signal="LONG",
                            signal_candidata="LONG"):
    return {
        "symbol": symbol, "total_score": total_score, "confidence": confidence,
        "signal": signal, "signal_candidata": signal_candidata,
        "score_fundamental": 25.0, "score_tecnico": 25.0, "score_derivados": 15.0,
        "score_sentimiento": 8.0, "score_macro": 7.0,
    }


def _pipeline(symbol, **kwargs):
    return {"symbol": symbol, "resultado": _mock_resultado_engine(symbol, **kwargs),
            "paper_resultado": None, "telegram_enviados": []}


@patch("app.notifications.crypto_telegram_commands.run_crypto_analysis")
def test_cripto_command_incluye_ambos_simbolos(mock_run):
    mock_run.side_effect = lambda symbol, **kw: _pipeline(symbol)

    mensaje = cripto_command()

    assert "BTCUSDT" in mensaje
    assert "ETHUSDT" in mensaje


@patch("app.notifications.crypto_telegram_commands.run_crypto_analysis")
def test_cripto_command_llama_de_solo_lectura(mock_run):
    mock_run.side_effect = lambda symbol, **kw: _pipeline(symbol)

    cripto_command()

    for llamada in mock_run.call_args_list:
        assert llamada.kwargs.get("persistir") is False
        assert llamada.kwargs.get("paper_trading") is False
        assert llamada.kwargs.get("notificar_telegram") is False


@patch("app.notifications.crypto_telegram_commands.run_crypto_analysis")
def test_cripto_command_muestra_candidata_descartada_por_riesgo(mock_run):
    mock_run.return_value = _pipeline("BTCUSDT", signal="NO_OPERAR", signal_candidata="LONG")

    mensaje = cripto_command()

    assert "descartada por riesgo/beneficio" in mensaje


@patch("app.notifications.crypto_telegram_commands.run_crypto_analysis")
def test_cripto_command_error_en_un_simbolo_no_rompe_el_otro(mock_run):
    def run(symbol, **kw):
        if symbol == "BTCUSDT":
            raise RuntimeError("fallo simulado")
        return _pipeline(symbol)

    mock_run.side_effect = run

    mensaje = cripto_command()

    assert "error generando el análisis" in mensaje
    assert "ETHUSDT" in mensaje
