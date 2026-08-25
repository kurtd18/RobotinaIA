"""Tests de app/scheduler/stock_scheduler_repository.py."""

from app.scheduler import stock_scheduler_repository as repo


def test_second_call_for_same_window_returns_false(db_path):
    primera = repo.intentar_registrar_ejecucion("2026-08-15", "09:00")
    segunda = repo.intentar_registrar_ejecucion("2026-08-15", "09:00")

    assert primera is True
    assert segunda is False


def test_different_hora_programada_same_fecha_both_return_true(db_path):
    resultado_1 = repo.intentar_registrar_ejecucion("2026-08-15", "09:00")
    resultado_2 = repo.intentar_registrar_ejecucion("2026-08-15", "14:00")

    assert resultado_1 is True
    assert resultado_2 is True


def test_stock_and_crypto_scheduler_windows_never_collide(db_path):
    """stock_scheduler_runs es una tabla separada de scheduler_runs
    (cripto) - la misma ventana no debe colisionar entre ambas."""
    from app.scheduler import repository as crypto_repo

    stock_resultado = repo.intentar_registrar_ejecucion("2026-08-15", "09:00")
    crypto_resultado = crypto_repo.intentar_registrar_ejecucion("2026-08-15", "09:00")

    assert stock_resultado is True
    assert crypto_resultado is True
