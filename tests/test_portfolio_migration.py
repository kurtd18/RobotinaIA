"""Tests de migrations/0001_portfolio_unify.py."""

import importlib
import sys
from pathlib import Path

from app.database.connection import get_connection

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
if str(_MIGRATIONS_DIR) not in sys.path:
    sys.path.insert(0, str(_MIGRATIONS_DIR))

portfolio_unify = importlib.import_module("0001_portfolio_unify")


def _insertar_paper_position(conn, symbol, status="OPEN", entry_price=100.0):
    conn.execute(
        """
        INSERT INTO paper_positions (
            symbol, direction, entry_price, stop_price, target_price,
            size_usdt, quantity, opened_at, status
        ) VALUES (?, 'LONG', ?, ?, ?, ?, ?, '2026-01-01T00:00:00', ?)
        """,
        (symbol, entry_price, entry_price * 0.95, entry_price * 1.1, 500.0, 5.0, status),
    )
    conn.commit()


def test_running_against_a_db_with_no_paper_positions_is_a_trivial_no_op(db_path):
    conn = get_connection()
    portfolio_antes = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    conn.close()

    exit_code = portfolio_unify.main()

    conn = get_connection()
    portfolio_despues = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    conn.close()

    assert exit_code == 0
    assert portfolio_despues == portfolio_antes


def test_migrates_three_recognized_paper_positions_into_five_total_portfolio_rows(db_path):
    conn = get_connection()
    # 2 filas ya existentes en portfolio (no relacionadas con esta migración)
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES ('AAPL', 10, 150.0, '2026-01-01', "
        "'OPEN', 'stock', 'AAPL')"
    )
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES ('MSFT', 5, 300.0, '2026-01-01', "
        "'OPEN', 'stock', 'MSFT')"
    )
    conn.commit()

    # 3 filas reconocidas en paper_positions
    _insertar_paper_position(conn, "BTCUSDT")
    _insertar_paper_position(conn, "ETHUSDT")
    _insertar_paper_position(conn, "SOLUSDT")
    conn.close()

    exit_code = portfolio_unify.main()

    conn = get_connection()
    total_portfolio = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    fila_btc = conn.execute(
        "SELECT asset_class, normalized_symbol FROM portfolio WHERE symbol = 'BTCUSDT'"
    ).fetchone()
    conn.close()

    assert exit_code == 0
    assert total_portfolio == 5
    assert fila_btc == ("crypto", "BTC")


def test_unrecognized_symbol_is_skipped_logged_and_reported(db_path, capsys):
    conn = get_connection()
    _insertar_paper_position(conn, "BTCUSDT")
    _insertar_paper_position(conn, "???-SYMBOL-RARO")
    conn.close()

    exit_code = portfolio_unify.main()
    captured = capsys.readouterr()

    conn = get_connection()
    total_portfolio = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    conn.close()

    assert exit_code == 0
    assert total_portfolio == 1  # solo la fila reconocida (BTCUSDT) se migró
    assert "???-SYMBOL-RARO" in captured.out  # reportado en el resumen final


def test_running_twice_skips_already_migrated_rows(db_path):
    conn = get_connection()
    _insertar_paper_position(conn, "BTCUSDT")
    conn.close()

    primer_exit = portfolio_unify.main()

    conn = get_connection()
    portfolio_tras_primera = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    conn.close()

    segundo_exit = portfolio_unify.main()

    conn = get_connection()
    portfolio_tras_segunda = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    migrated_marker = conn.execute(
        "SELECT migrated_to_portfolio_id FROM paper_positions WHERE symbol = 'BTCUSDT'"
    ).fetchone()[0]
    conn.close()

    assert primer_exit == 0
    assert segundo_exit == 0
    assert portfolio_tras_primera == 1
    assert portfolio_tras_segunda == 1  # la segunda corrida no migró de nuevo
    assert migrated_marker is not None
