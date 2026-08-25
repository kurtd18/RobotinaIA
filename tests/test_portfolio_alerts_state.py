"""Tests de la integración de portfolio_alerts.py con alert_state.py (E5-T2)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from app.alerts import alert_state, portfolio_alerts
from app.database.connection import get_connection

TZ_BOGOTA = ZoneInfo("America/Bogota")


def _crear_posicion(conn, symbol="BTC-USD"):
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES (?, 1, 100.0, '2026-01-01', 'OPEN', 'crypto', ?)",
        (symbol, symbol),
    )
    conn.commit()
    return conn.execute("SELECT id FROM portfolio WHERE symbol = ?", (symbol,)).fetchone()[0]


def test_two_cycles_more_than_6h_apart_no_material_change_send_exactly_two(db_path, monkeypatch):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    mock_enviar = MagicMock(return_value=200)
    monkeypatch.setattr(portfolio_alerts, "enviar_mensaje_telegram", mock_enviar)

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    monkeypatch.setattr(alert_state, "_ahora", lambda: t0)
    portfolio_alerts._revisar_stop_loss(position_id, "BTC-USD", 95.0, stop_loss=100.0)

    t1 = t0 + timedelta(hours=7)  # más de 6h, mismo precio (sin cambio material)
    monkeypatch.setattr(alert_state, "_ahora", lambda: t1)
    portfolio_alerts._revisar_stop_loss(position_id, "BTC-USD", 95.0, stop_loss=100.0)

    assert mock_enviar.call_count == 2  # ni 0 (el bug de hoy) ni uno por ciclo


def test_new_low_between_cycles_notifies_immediately_regardless_of_window(db_path, monkeypatch):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    mock_enviar = MagicMock(return_value=200)
    monkeypatch.setattr(portfolio_alerts, "enviar_mensaje_telegram", mock_enviar)

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    monkeypatch.setattr(alert_state, "_ahora", lambda: t0)
    portfolio_alerts._revisar_stop_loss(position_id, "BTC-USD", 95.0, stop_loss=100.0)

    t1 = t0 + timedelta(minutes=5)  # muy poco tiempo, muy por debajo de las 6h
    monkeypatch.setattr(alert_state, "_ahora", lambda: t1)
    precio_nuevo_minimo = 95.0 * 0.99  # 1% más bajo, supera el umbral de 0.5%
    portfolio_alerts._revisar_stop_loss(
        position_id, "BTC-USD", precio_nuevo_minimo, stop_loss=100.0
    )

    assert mock_enviar.call_count == 2  # ambas notificaron pese a la ventana de 6h


def test_price_recovery_resolves_and_next_breach_notifies_immediately(db_path, monkeypatch):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    mock_enviar = MagicMock(return_value=200)
    monkeypatch.setattr(portfolio_alerts, "enviar_mensaje_telegram", mock_enviar)

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    monkeypatch.setattr(alert_state, "_ahora", lambda: t0)
    portfolio_alerts._revisar_stop_loss(position_id, "BTC-USD", 95.0, stop_loss=100.0)
    assert mock_enviar.call_count == 1

    t1 = t0 + timedelta(minutes=5)
    monkeypatch.setattr(alert_state, "_ahora", lambda: t1)
    portfolio_alerts._revisar_stop_loss(position_id, "BTC-USD", 105.0, stop_loss=100.0)  # recupera
    assert mock_enviar.call_count == 1  # recuperarse no notifica

    conn = get_connection()
    status = conn.execute(
        "SELECT status FROM alert_state WHERE position_id = ? AND alert_type = 'stop_loss'",
        (position_id,),
    ).fetchone()[0]
    conn.close()
    assert status == "resolved"

    t2 = t1 + timedelta(minutes=5)  # muy poco después, lejos de las 6h de recordatorio
    monkeypatch.setattr(alert_state, "_ahora", lambda: t2)
    portfolio_alerts._revisar_stop_loss(position_id, "BTC-USD", 95.0, stop_loss=100.0)  # rompe otra vez

    assert mock_enviar.call_count == 2  # notifica de inmediato, no espera el recordatorio periódico
