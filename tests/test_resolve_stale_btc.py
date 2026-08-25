"""Tests de migrations/0002_resolve_stale_btc.py."""

import importlib
import sys
from unittest.mock import patch
from pathlib import Path

import pytest

from app.database.connection import get_connection

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
if str(_MIGRATIONS_DIR) not in sys.path:
    sys.path.insert(0, str(_MIGRATIONS_DIR))

resolve_stale_btc = importlib.import_module("0002_resolve_stale_btc")


def _insertar_posicion_btc(conn, asset_class="stock", normalized_symbol="BTC-USD"):
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, target_price, "
        "stop_loss, status, asset_class, normalized_symbol) VALUES "
        "('BTC-USD', 1, 118000, '2026-01-01', 122000, 116000, 'OPEN', ?, ?)",
        (asset_class, normalized_symbol),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM portfolio WHERE symbol = 'BTC-USD'"
    ).fetchone()[0]


def _fila_completa(conn, position_id):
    return conn.execute(
        "SELECT status, asset_class, normalized_symbol, sell_price, sell_date "
        "FROM portfolio WHERE id = ?",
        (position_id,),
    ).fetchone()


def test_no_flags_prints_both_options_exits_2_and_touches_nothing(db_path, capsys):
    conn = get_connection()
    position_id = _insertar_posicion_btc(conn)
    fila_antes = _fila_completa(conn, position_id)
    conn.close()

    exit_code = resolve_stale_btc.main([])
    captured = capsys.readouterr()

    conn = get_connection()
    fila_despues = _fila_completa(conn, position_id)
    conn.close()

    assert exit_code == 2
    assert "--action=migrate" in captured.out
    assert "--action=close" in captured.out
    assert fila_antes == fila_despues


def test_action_migrate_leaves_open_and_sets_asset_class(db_path):
    conn = get_connection()
    position_id = _insertar_posicion_btc(conn, asset_class="stock", normalized_symbol="BTC-USD")
    conn.close()

    exit_code = resolve_stale_btc.main(["--action=migrate", f"--position-id={position_id}"])

    conn = get_connection()
    row = _fila_completa(conn, position_id)
    conn.close()

    assert exit_code == 0
    assert row[0] == "OPEN"
    assert row[1] == "crypto"
    assert row[2] == "BTC"


def test_action_migrate_is_idempotent_when_already_unified(db_path):
    conn = get_connection()
    position_id = _insertar_posicion_btc(conn, asset_class="crypto", normalized_symbol="BTC")
    conn.close()

    exit_code = resolve_stale_btc.main(["--action=migrate", f"--position-id={position_id}"])

    conn = get_connection()
    row = _fila_completa(conn, position_id)
    conn.close()

    assert exit_code == 0
    assert row[0] == "OPEN"
    assert row[1] == "crypto"
    assert row[2] == "BTC"


def test_action_close_without_confirm_exits_2_and_touches_nothing(db_path, capsys):
    conn = get_connection()
    position_id = _insertar_posicion_btc(conn, asset_class="crypto", normalized_symbol="BTC")
    fila_antes = _fila_completa(conn, position_id)
    conn.close()

    exit_code = resolve_stale_btc.main(["--action=close", f"--position-id={position_id}"])
    captured = capsys.readouterr()

    conn = get_connection()
    fila_despues = _fila_completa(conn, position_id)
    conn.close()

    assert exit_code == 2
    assert "--confirm-close" in captured.out
    assert fila_antes == fila_despues


def test_action_close_with_confirm_closes_position_with_yahoo_price(db_path):
    conn = get_connection()
    position_id = _insertar_posicion_btc(conn, asset_class="crypto", normalized_symbol="BTC")
    conn.close()

    with patch("app.providers.yahoo_provider.yf.Ticker") as mock_ticker_cls:
        import pandas as pd

        idx = pd.date_range("2026-01-01", periods=1, freq="5min", tz="UTC")
        mock_ticker_cls.return_value.history.return_value = pd.DataFrame(
            {"Open": [125000.0], "High": [125000.0], "Low": [125000.0],
             "Close": [125000.0], "Volume": [1.0]},
            index=idx,
        )

        exit_code = resolve_stale_btc.main(
            ["--action=close", "--confirm-close", f"--position-id={position_id}"]
        )

    conn = get_connection()
    row = _fila_completa(conn, position_id)
    conn.close()

    assert exit_code == 0
    assert row[0] == "CLOSED"
    assert row[3] == 125000.0  # sell_price viene de YahooProvider
    assert row[4] is not None  # sell_date
