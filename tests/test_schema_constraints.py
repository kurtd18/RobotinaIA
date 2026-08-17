"""Tests de app/database/schema.py: constraints FK/CHECK y user_version."""

import sqlite3

from app.database.connection import get_connection
from app.database.schema import create_tables


def test_foreign_key_check_returns_no_rows_after_migration(db_path):
    conn = get_connection()
    try:
        rows = conn.execute("PRAGMA foreign_key_check;").fetchall()
    finally:
        conn.close()
    assert rows == []


def test_insert_portfolio_decisions_with_nonexistent_position_raises(db_path):
    conn = get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO portfolio_decisions (position_id, decision, timestamp) "
                "VALUES (999999, 'HOLD', '2026-01-01T00:00:00');"
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_insert_signals_with_invalid_signal_value_raises(db_path):
    conn = get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO signals (symbol, score, signal, price, timestamp) "
                "VALUES ('AAA', 10, 'NOT_A_REAL_SIGNAL', 1.0, '2026-01-01T00:00:00');"
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_insert_signals_accepts_expired_value(db_path):
    """EXPIRED es un valor real en uso (signal_manager.py,
    limpiar_senales_viejas.py) - el CHECK no debe rechazarlo."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO signals (symbol, score, signal, price, timestamp) "
            "VALUES ('AAA', 10, 'EXPIRED', 1.0, '2026-01-01T00:00:00');"
        )
        conn.commit()
    finally:
        conn.close()


def test_insert_portfolio_with_invalid_status_raises(db_path):
    conn = get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status) "
                "VALUES ('AAA', 1, 1.0, '2026-01-01', 'NOT_A_REAL_STATUS');"
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_create_tables_is_idempotent_user_version_unchanged(db_path):
    conn = get_connection()
    version_before = conn.execute("PRAGMA user_version;").fetchone()[0]
    conn.close()

    create_tables()

    conn = get_connection()
    version_after = conn.execute("PRAGMA user_version;").fetchone()[0]
    conn.close()

    assert version_before == version_after


def test_user_version_is_at_least_1(db_path):
    conn = get_connection()
    version = conn.execute("PRAGMA user_version;").fetchone()[0]
    conn.close()
    assert version >= 1


def test_scheduler_and_paper_trading_tables_exist(db_path):
    """schema.py ahora crea también scheduler_runs y paper_positions
    (movidas desde sus módulos), más las tablas nuevas para Épicas 5/6."""
    conn = get_connection()
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
    finally:
        conn.close()

    for expected in (
        "scheduler_runs",
        "paper_positions",
        "stock_scheduler_runs",
        "alert_state",
    ):
        assert expected in tables
