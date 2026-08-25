"""Tests de app/notifications/commands.py."""

from unittest.mock import patch

from app.database.connection import get_connection
from app.notifications import commands, crypto_telegram_commands
from app.services import portfolio_service


def _crear_posicion(conn, symbol, asset_class):
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES (?, 1, 100.0, '2026-01-01', 'OPEN', ?, ?)",
        (symbol, asset_class, symbol),
    )
    conn.commit()


def test_portfolio_command_lists_both_asset_classes(db_path):
    conn = get_connection()
    _crear_posicion(conn, "AAPL", "stock")
    _crear_posicion(conn, "BTC-USD", "crypto")
    conn.close()

    mensaje = commands.portfolio_command()

    assert "AAPL" in mensaje
    assert "BTC-USD" in mensaje
    assert "stock" in mensaje
    assert "crypto" in mensaje


def test_comprar_command_uses_portfolio_service_add_position(db_path):
    conn = get_connection()
    conn.execute(
        "INSERT INTO signals (symbol, score, signal, price, timestamp) "
        "VALUES ('AAPL', 80, 'PENDING', 150.0, '2026-01-01T00:00:00')"
    )
    conn.commit()
    signal_id = conn.execute("SELECT id FROM signals WHERE symbol='AAPL'").fetchone()[0]
    conn.close()

    with patch("app.notifications.commands.mark_as_executed") as mock_mark:
        mensaje = commands.comprar_command(signal_id, 10)

    assert "POSICIÓN AGREGADA" in mensaje
    mock_mark.assert_called_once_with(signal_id)

    posiciones = portfolio_service.get_open_positions()
    assert len(posiciones) == 1
    assert posiciones[0]["symbol"] == "AAPL"
    assert posiciones[0]["asset_class"] == "stock"


def test_comprar_command_crypto_signal_gets_crypto_asset_class(db_path):
    conn = get_connection()
    conn.execute(
        "INSERT INTO signals (symbol, score, signal, price, timestamp) "
        "VALUES ('BTC-USD', 80, 'PENDING', 50000.0, '2026-01-01T00:00:00')"
    )
    conn.commit()
    signal_id = conn.execute("SELECT id FROM signals WHERE symbol='BTC-USD'").fetchone()[0]
    conn.close()

    with patch("app.notifications.commands.mark_as_executed"):
        commands.comprar_command(signal_id, 1)

    posiciones = portfolio_service.get_open_positions()
    assert posiciones[0]["asset_class"] == "crypto"


def test_comprar_command_unknown_signal_returns_message_without_creating_position(db_path):
    mensaje = commands.comprar_command(999999, 1)

    assert "No se encontró la señal" in mensaje
    assert portfolio_service.get_open_positions() == []


def test_sell_command_closes_position_via_portfolio_service(db_path):
    position_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")

    mensaje = commands.sell_command(position_id, 160.0)

    assert "POSICIÓN CERRADA" in mensaje
    assert portfolio_service.get_open_positions() == []


def test_vender_command_closes_and_registers_decision(db_path):
    position_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")

    mensaje = commands.vender_command(position_id, 140.0)

    assert "POSICIÓN CERRADA (por stop loss)" in mensaje

    conn = get_connection()
    decision = conn.execute(
        "SELECT decision FROM portfolio_decisions WHERE position_id = ?", (position_id,)
    ).fetchone()
    conn.close()
    assert decision == ("VENDER",)


def test_mantener_command_registers_decision_without_closing(db_path):
    position_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")

    mensaje = commands.mantener_command(position_id)

    assert "MANTENER" in mensaje
    assert len(portfolio_service.get_open_positions()) == 1


def test_cripto_command_is_the_same_function_moved_unchanged():
    assert commands.cripto_command is crypto_telegram_commands.cripto_command


def test_analisis_command_rejects_unknown_symbol(db_path):
    mensaje = commands.analisis_command("NOEXISTE")
    assert "no está en la lista de activos monitoreados" in mensaje


def test_commands_dict_has_all_seven_entries():
    assert set(commands.COMMANDS.keys()) == {
        "portfolio", "comprar", "sell", "vender", "mantener", "analisis", "cripto",
    }
