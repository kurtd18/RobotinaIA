"""Tests de app/database/connection.py: WAL, busy_timeout, foreign_keys."""

import sqlite3
import threading
import time

from app.database.connection import BUSY_TIMEOUT_MS, get_connection


def test_get_connection_reports_wal_journal_mode(db_path):
    conn = get_connection()
    try:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"
    finally:
        conn.close()


def test_get_connection_reports_busy_timeout(db_path):
    conn = get_connection()
    try:
        timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert timeout == BUSY_TIMEOUT_MS == 5000
    finally:
        conn.close()


def test_get_connection_reports_foreign_keys_on(db_path):
    conn = get_connection()
    try:
        foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert foreign_keys == 1
    finally:
        conn.close()


def test_concurrent_write_succeeds_once_first_commits(db_path):
    """Dos hilos escriben casi al mismo tiempo; con busy_timeout el
    segundo debe esperar y tener éxito en vez de lanzar
    'database is locked'."""
    errors = []
    started = threading.Event()

    def hold_write_transaction():
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                "INSERT INTO signals (symbol, score, signal, price, timestamp) "
                "VALUES ('AAA', 10, 'PENDING', 1.0, '2026-01-01T00:00:00');"
            )
            started.set()
            time.sleep(0.2)
            conn.commit()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)
        finally:
            conn.close()

    def second_writer():
        started.wait(timeout=2)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO signals (symbol, score, signal, price, timestamp) "
                "VALUES ('BBB', 20, 'PENDING', 2.0, '2026-01-01T00:00:00');"
            )
            conn.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=hold_write_transaction)
    t2 = threading.Thread(target=second_writer)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"la segunda conexión falló en vez de esperar: {errors}"

    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE symbol IN ('AAA', 'BBB');"
        ).fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_get_connection_raises_instead_of_returning_misconfigured_connection(
    db_path, monkeypatch
):
    """Si una PRAGMA no aplica correctamente, get_connection() debe
    propagar el error, nunca devolver una conexión a medio configurar."""

    real_connect = sqlite3.connect

    class _FakeCursor:
        def __init__(self, value):
            self._value = value

        def fetchone(self):
            return (self._value,)

    class _FakeConnection:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def execute(self, sql, *args, **kwargs):
            if "journal_mode" in sql:
                return _FakeCursor("delete")  # simula que WAL no se activó
            return self._real_conn.execute(sql, *args, **kwargs)

        def close(self):
            self._real_conn.close()

    def fake_connect(*args, **kwargs):
        return _FakeConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    try:
        get_connection()
        assert False, "se esperaba sqlite3.OperationalError"
    except sqlite3.OperationalError as exc:
        assert "WAL" in str(exc) or "wal" in str(exc).lower()
