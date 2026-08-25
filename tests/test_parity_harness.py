"""Tests de scripts/parity_harness_portfolio.py."""

import importlib
import sys
from pathlib import Path

from app.database.connection import get_connection
from app.services.fee_config import FlatPercentageFeeConfig

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

parity_harness = importlib.import_module("parity_harness_portfolio")


def _insertar_closed(conn, symbol, buy_price, sell_price, quantity, asset_class):
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "sell_price, sell_date, asset_class, normalized_symbol) VALUES "
        "(?, ?, ?, '2026-01-01', 'CLOSED', ?, '2026-01-02', ?, ?)",
        (symbol, quantity, buy_price, sell_price, asset_class, symbol),
    )
    conn.commit()


def test_no_closed_positions_is_zero_mismatches(db_path):
    exit_code = parity_harness.main()
    assert exit_code == 0


def test_matching_closed_positions_report_zero_mismatches(db_path):
    conn = get_connection()
    _insertar_closed(conn, "AAPL", 150.0, 160.0, 10, "stock")
    _insertar_closed(conn, "BTC-USD", 50000, 52000, 0.1, "crypto")
    conn.close()

    exit_code = parity_harness.main()

    assert exit_code == 0


def test_injected_mismatch_is_detected_reported_with_row_id_and_values_and_exits_1(
    db_path, monkeypatch, capsys
):
    conn = get_connection()
    position_id_insertado = None
    _insertar_closed(conn, "AAPL", 150.0, 160.0, 10, "stock")
    position_id_insertado = conn.execute(
        "SELECT id FROM portfolio WHERE symbol = 'AAPL'"
    ).fetchone()[0]
    conn.close()

    # Inyecta una discrepancia real: una comisión distinta de cero para
    # 'stock' hace que el camino nuevo diverja del viejo.
    monkeypatch.setitem(
        parity_harness._FEE_CONFIGS,
        "stock",
        FlatPercentageFeeConfig(fee_pct=0.01, configured=True),
    )

    exit_code = parity_harness.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert f"id={position_id_insertado}" in captured.out
    assert "viejo=" in captured.out and "nuevo=" in captured.out
