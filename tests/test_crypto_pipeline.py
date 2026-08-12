"""
Pruebas de la función central run_crypto_analysis (Fase 10). Todo
mockeado - no dependen de Internet.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.scheduler.crypto_pipeline import run_crypto_analysis


def _resultado(signal="LONG", cambio_senal=None):
    return {
        "symbol": "BTCUSDT", "total_score": 80.0, "confidence": 75.0, "signal": signal,
        "cambio_senal": cambio_senal, "razones": ["r"], "risk_reward": {"disponible": True, "ratio": 2.0},
    }


@patch("app.scheduler.crypto_pipeline.notificar")
@patch("app.scheduler.crypto_pipeline.PaperTradingEngine")
def test_ejecuta_scoring_paper_y_notificaciones_en_orden(mock_paper_cls, mock_notificar):
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado()
    paper_engine = MagicMock()
    paper_engine.procesar.return_value = {"posiciones_cerradas": [], "posicion_abierta": {"direction": "LONG"}}
    mock_notificar.return_value = ["mensaje"]

    resultado = run_crypto_analysis("BTCUSDT", scoring_engine=scoring_engine, paper_engine=paper_engine)

    scoring_engine.analizar.assert_called_once_with("BTCUSDT", persistir=True)
    paper_engine.procesar.assert_called_once()
    mock_notificar.assert_called_once()
    assert resultado["telegram_enviados"] == ["mensaje"]


def test_paper_trading_false_no_llama_paper_engine():
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado()
    paper_engine = MagicMock()

    run_crypto_analysis("BTCUSDT", paper_trading=False, scoring_engine=scoring_engine, paper_engine=paper_engine)

    paper_engine.procesar.assert_not_called()


@patch("app.scheduler.crypto_pipeline.notificar")
def test_notificar_telegram_false_no_llama_notificar(mock_notificar):
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado()

    run_crypto_analysis("BTCUSDT", paper_trading=False, notificar_telegram=False, scoring_engine=scoring_engine)

    mock_notificar.assert_not_called()


def test_persistir_false_se_propaga_al_scoring_engine():
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado()

    run_crypto_analysis("BTCUSDT", persistir=False, paper_trading=False, notificar_telegram=False,
                         scoring_engine=scoring_engine)

    scoring_engine.analizar.assert_called_once_with("BTCUSDT", persistir=False)


def test_fallo_de_paper_trading_no_rompe_el_pipeline():
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado()
    paper_engine = MagicMock()
    paper_engine.procesar.side_effect = RuntimeError("fallo simulado de paper trading")

    resultado = run_crypto_analysis("BTCUSDT", scoring_engine=scoring_engine, paper_engine=paper_engine,
                                     notificar_telegram=False)

    assert resultado["paper_resultado"]["error"] == "fallo simulado de paper trading"


@patch("app.scheduler.crypto_pipeline.notificar")
def test_fallo_de_telegram_no_rompe_el_pipeline(mock_notificar):
    mock_notificar.side_effect = RuntimeError("fallo simulado de telegram")
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado()

    resultado = run_crypto_analysis("BTCUSDT", paper_trading=False, scoring_engine=scoring_engine)

    assert resultado["telegram_enviados"] == []  # no se cae, solo queda vacío


def test_cambio_de_senal_se_propaga_intacto_en_el_resultado():
    scoring_engine = MagicMock()
    scoring_engine.analizar.return_value = _resultado(cambio_senal={"de": "NO_OPERAR", "a": "LONG"})

    resultado = run_crypto_analysis("BTCUSDT", paper_trading=False, notificar_telegram=False,
                                     scoring_engine=scoring_engine)

    assert resultado["resultado"]["cambio_senal"] == {"de": "NO_OPERAR", "a": "LONG"}


def test_resultado_de_paper_trading_recibe_el_resultado_del_scoring():
    scoring_engine = MagicMock()
    resultado_scoring = _resultado()
    scoring_engine.analizar.return_value = resultado_scoring
    paper_engine = MagicMock()
    paper_engine.procesar.return_value = {"posiciones_cerradas": [], "posicion_abierta": None}

    run_crypto_analysis("BTCUSDT", notificar_telegram=False, scoring_engine=scoring_engine, paper_engine=paper_engine)

    paper_engine.procesar.assert_called_once_with("BTCUSDT", resultado_scoring)
