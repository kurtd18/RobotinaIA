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
                "INSERT INTO portfolio "
                "(symbol, quantity, buy_price, buy_date, status, asset_class, normalized_symbol) "
                "VALUES ('AAA', 1, 1.0, '2026-01-01', 'NOT_A_REAL_STATUS', 'stock', 'AAA');"
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_insert_portfolio_asset_class_option_raises(db_path):
    conn = get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO portfolio "
                "(symbol, quantity, buy_price, buy_date, asset_class, normalized_symbol) "
                "VALUES ('AAA', 1, 1.0, '2026-01-01', 'option', 'AAA');"
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def _construir_portfolio_pre_migracion_002(conn):
    """Recrea la forma de portfolio tal como la deja la migración 1
    (status con CHECK, pero sin asset_class/normalized_symbol/fee) -
    el estado "de antes" contra el que corre la migración 2."""
    conn.execute(
        """
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            buy_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            target_price REAL,
            stop_loss REAL,
            status TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
            sell_price REAL,
            sell_date TEXT,
            alerta_stop_enviada INTEGER DEFAULT 0
        )
        """
    )
    # apply_migrations() sigue de largo hasta la migración más nueva
    # disponible (hoy, la 3, que toca alert_state) - esta tabla base
    # tiene que existir para que ese paso no falle, aunque este test
    # solo le interese verificar la migración 2.
    conn.execute(
        """
        CREATE TABLE alert_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'first_trigger',
            extreme_price REAL,
            first_triggered_at TEXT NOT NULL,
            last_notified_at TEXT,
            resolved_at TEXT
        )
        """
    )
    conn.execute("PRAGMA user_version=1;")


def test_migration_sets_portfolio_asset_class_crypto_for_btc_usd_row(tmp_path):
    """La fila BTC-USD (mismo símbolo que id=2 en la base real) debe
    quedar asset_class='crypto', normalized_symbol='BTC' tras correr la
    migración 2 - probando la migración en sí, no solo el esquema final."""
    from app.database.migrations import apply_migrations

    conn = sqlite3.connect(tmp_path / "premig.db")
    try:
        _construir_portfolio_pre_migracion_002(conn)
        conn.execute(
            "INSERT INTO portfolio (id, symbol, quantity, buy_price, buy_date, status) "
            "VALUES (2, 'BTC-USD', 1, 118000, '2026-01-01', 'OPEN');"
        )
        conn.commit()

        apply_migrations(conn)

        row = conn.execute(
            "SELECT asset_class, normalized_symbol FROM portfolio WHERE id = 2;"
        ).fetchone()
    finally:
        conn.close()

    assert row == ("crypto", "BTC")


def test_migration_sets_portfolio_asset_class_stock_for_stock_row(tmp_path):
    from app.database.migrations import apply_migrations

    conn = sqlite3.connect(tmp_path / "premig.db")
    try:
        _construir_portfolio_pre_migracion_002(conn)
        conn.execute(
            "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status) "
            "VALUES ('ECOPETROL.CL', 100, 2000, '2026-01-01', 'OPEN');"
        )
        conn.commit()

        apply_migrations(conn)

        row = conn.execute(
            "SELECT asset_class, normalized_symbol FROM portfolio WHERE symbol = 'ECOPETROL.CL';"
        ).fetchone()
    finally:
        conn.close()

    assert row == ("stock", "ECOPETROL.CL")


def test_migration_002_is_idempotent_when_run_twice(tmp_path):
    from app.database.migrations import apply_migrations, current_version

    conn = sqlite3.connect(tmp_path / "premig.db")
    try:
        _construir_portfolio_pre_migracion_002(conn)
        conn.execute(
            "INSERT INTO portfolio (id, symbol, quantity, buy_price, buy_date, status) "
            "VALUES (2, 'BTC-USD', 1, 118000, '2026-01-01', 'OPEN');"
        )
        conn.commit()

        apply_migrations(conn)
        version_after_first = current_version(conn)
        row_after_first = conn.execute(
            "SELECT asset_class, normalized_symbol FROM portfolio WHERE id = 2;"
        ).fetchone()

        apply_migrations(conn)
        version_after_second = current_version(conn)
        row_after_second = conn.execute(
            "SELECT asset_class, normalized_symbol FROM portfolio WHERE id = 2;"
        ).fetchone()
    finally:
        conn.close()

    assert version_after_first == version_after_second
    assert row_after_first == row_after_second == ("crypto", "BTC")


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


def test_insert_alert_state_with_invalid_status_raises(db_path):
    conn = get_connection()
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES ('AAA', 1, 1.0, '2026-01-01', "
        "'OPEN', 'stock', 'AAA')"
    )
    conn.commit()
    position_id = conn.execute("SELECT id FROM portfolio WHERE symbol='AAA'").fetchone()[0]
    try:
        try:
            conn.execute(
                "INSERT INTO alert_state (position_id, alert_type, status, first_triggered_at) "
                "VALUES (?, 'stop_loss', 'NOT_A_REAL_STATUS', '2026-01-01T00:00:00')",
                (position_id,),
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_insert_alert_state_duplicate_position_and_type_raises(db_path):
    conn = get_connection()
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES ('AAA', 1, 1.0, '2026-01-01', "
        "'OPEN', 'stock', 'AAA')"
    )
    conn.commit()
    position_id = conn.execute("SELECT id FROM portfolio WHERE symbol='AAA'").fetchone()[0]
    try:
        conn.execute(
            "INSERT INTO alert_state (position_id, alert_type, first_triggered_at) "
            "VALUES (?, 'stop_loss', '2026-01-01T00:00:00')",
            (position_id,),
        )
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO alert_state (position_id, alert_type, first_triggered_at) "
                "VALUES (?, 'stop_loss', '2026-01-01T01:00:00')",
                (position_id,),
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError (UNIQUE)"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_insert_alert_state_with_nonexistent_position_raises(db_path):
    conn = get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO alert_state (position_id, alert_type, first_triggered_at) "
                "VALUES (999999, 'stop_loss', '2026-01-01T00:00:00')"
            )
            conn.commit()
            assert False, "se esperaba sqlite3.IntegrityError"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


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
