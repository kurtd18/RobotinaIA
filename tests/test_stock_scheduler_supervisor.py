"""Tests de app/scheduler/supervisor.py."""

from unittest.mock import MagicMock, patch

from app.scheduler.supervisor import run_supervised


def test_succeeds_on_third_attempt_calls_exactly_three_times_with_increasing_sleep():
    target = MagicMock(
        side_effect=[ConnectionError("falla 1"), ConnectionError("falla 2"), None]
    )

    with patch("app.scheduler.supervisor.time.sleep") as mock_sleep, \
         patch("app.scheduler.supervisor.enviar_mensaje_telegram") as mock_enviar:
        run_supervised(target, "stock_scheduler", max_restarts=5, backoff_base_seconds=10)

    assert target.call_count == 3
    mock_enviar.assert_not_called()

    # 2 esperas (tras el intento 1 y el intento 2), creciendo: 10, 20
    assert mock_sleep.call_count == 2
    esperas = [llamada.args[0] for llamada in mock_sleep.call_args_list]
    assert esperas == [10, 20]
    assert esperas[0] < esperas[1]


def test_always_raising_calls_exactly_max_restarts_times_then_escalates_once():
    target = MagicMock(side_effect=RuntimeError("siempre falla"))

    with patch("app.scheduler.supervisor.time.sleep"), \
         patch("app.scheduler.supervisor.enviar_mensaje_telegram") as mock_enviar:
        run_supervised(target, "stock_scheduler", max_restarts=4, backoff_base_seconds=1)

    assert target.call_count == 4
    mock_enviar.assert_called_once()
    # No debe volver a llamar target() tras la escalación.


def test_escalation_message_includes_exception_type_message_and_restart_count():
    target = MagicMock(side_effect=RuntimeError("algo se rompió feo"))

    with patch("app.scheduler.supervisor.time.sleep"), \
         patch("app.scheduler.supervisor.enviar_mensaje_telegram") as mock_enviar:
        run_supervised(target, "stock_scheduler", max_restarts=3, backoff_base_seconds=1)

    mensaje_enviado = mock_enviar.call_args.args[0]
    assert "RuntimeError" in mensaje_enviado
    assert "algo se rompió feo" in mensaje_enviado
    assert "3" in mensaje_enviado  # cantidad de intentos agotados


def test_wait_is_capped_at_thirty_minutes():
    target = MagicMock(side_effect=RuntimeError("siempre falla"))

    with patch("app.scheduler.supervisor.time.sleep") as mock_sleep, \
         patch("app.scheduler.supervisor.enviar_mensaje_telegram"):
        run_supervised(target, "stock_scheduler", max_restarts=10, backoff_base_seconds=600)

    esperas = [llamada.args[0] for llamada in mock_sleep.call_args_list]
    assert max(esperas) <= 30 * 60
    assert esperas[-1] == 30 * 60  # con base=600 el backoff exponencial supera el tope rápido
