"""Tests de app/services/signal_query_service.py."""

from app.database.connection import get_connection
from app.services.signal_query_service import listar_senales


def _insertar_senal(conn, symbol, score, signal, price):
    conn.execute(
        "INSERT INTO signals (symbol, score, signal, price, timestamp) "
        "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00')",
        (symbol, score, signal, price),
    )
    conn.commit()


def test_listar_senales_returns_three_rows_with_expected_columns(db_path):
    conn = get_connection()
    _insertar_senal(conn, "AAPL", 80, "PENDING", 150.0)
    _insertar_senal(conn, "MSFT", 60, "EXECUTED", 300.0)
    _insertar_senal(conn, "BTC-USD", 90, "PENDING", 50000.0)
    conn.close()

    df = listar_senales()

    assert len(df) == 3
    assert list(df.columns) == ["id", "symbol", "score", "signal", "price", "timestamp"]


def test_listar_senales_orders_most_recent_first(db_path):
    conn = get_connection()
    _insertar_senal(conn, "AAPL", 80, "PENDING", 150.0)
    _insertar_senal(conn, "MSFT", 60, "EXECUTED", 300.0)
    conn.close()

    df = listar_senales()

    assert df.iloc[0]["symbol"] == "MSFT"  # el insertado más reciente (mayor id) va primero


def test_listar_senales_returns_empty_dataframe_when_no_signals(db_path):
    df = listar_senales()

    assert df.empty
