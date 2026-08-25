"""Tests de app/alerts/alert_state.py."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.alerts import alert_state
from app.database.connection import get_connection

TZ_BOGOTA = ZoneInfo("America/Bogota")


def _crear_posicion(conn, symbol="BTC-USD", asset_class="crypto"):
    conn.execute(
        "INSERT INTO portfolio (symbol, quantity, buy_price, buy_date, status, "
        "asset_class, normalized_symbol) VALUES (?, 1, 100.0, '2026-01-01', 'OPEN', ?, ?)",
        (symbol, asset_class, symbol),
    )
    conn.commit()
    return conn.execute("SELECT id FROM portfolio WHERE symbol = ?", (symbol,)).fetchone()[0]


def _estado(conn, position_id, alert_type="stop_loss"):
    return conn.execute(
        "SELECT status, extreme_price, last_notified_at, resolved_at FROM alert_state "
        "WHERE position_id = ? AND alert_type = ?",
        (position_id, alert_type),
    ).fetchone()


def test_first_trigger_inserts_and_should_notify_true(db_path):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    alert_state.record_trigger(position_id, "stop_loss", 95.0, now=t0)

    conn = get_connection()
    status, extreme_price, last_notified_at, resolved_at = _estado(conn, position_id)
    conn.close()

    assert status == "first_trigger"
    assert extreme_price == 95.0
    assert last_notified_at is None  # todavía no lo consumió should_notify
    assert resolved_at is None

    assert alert_state.should_notify(position_id, "stop_loss", now=t0) is True


def test_no_material_change_within_window_leaves_status_and_returns_false(db_path):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    alert_state.record_trigger(position_id, "stop_loss", 95.0, now=t0)
    assert alert_state.should_notify(position_id, "stop_loss", now=t0) is True  # consume la notif.

    t1 = t0 + timedelta(hours=1)
    precio_casi_igual = 95.0 * 0.999  # dentro del 0.5%
    alert_state.record_trigger(position_id, "stop_loss", precio_casi_igual, now=t1)

    conn = get_connection()
    status_despues, extreme_price_despues, _, _ = _estado(conn, position_id)
    conn.close()

    assert status_despues == "first_trigger"  # sin cambio
    assert extreme_price_despues == 95.0  # sin cambio

    assert alert_state.should_notify(position_id, "stop_loss", now=t1) is False


def test_material_worsening_sets_new_extreme_and_notifies(db_path):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    alert_state.record_trigger(position_id, "stop_loss", 95.0, now=t0)
    alert_state.should_notify(position_id, "stop_loss", now=t0)

    t1 = t0 + timedelta(hours=1)
    precio_peor = 95.0 * 0.99  # 1% más bajo, por encima del umbral de 0.5%
    alert_state.record_trigger(position_id, "stop_loss", precio_peor, now=t1)

    conn = get_connection()
    status, extreme_price, last_notified_at, _ = _estado(conn, position_id)
    conn.close()

    assert status == "new_extreme"
    assert extreme_price == precio_peor
    assert last_notified_at is None  # reseteado, todavía no notificado

    assert alert_state.should_notify(position_id, "stop_loss", now=t1) is True


def test_target_direction_is_opposite_of_stop_loss(db_path):
    """Para 'target' un precio MÁS ALTO es el que cuenta como extremo -
    justo lo contrario de stop_loss. Si la dirección estuviera invertida
    por error, este test lo detecta."""
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    alert_state.record_trigger(position_id, "target", 110.0, now=t0)
    alert_state.should_notify(position_id, "target", now=t0)

    t1 = t0 + timedelta(hours=1)

    # Un precio más BAJO no debe contar como nuevo extremo para 'target'.
    alert_state.record_trigger(position_id, "target", 100.0, now=t1)
    conn = get_connection()
    status_tras_bajada, extreme_tras_bajada, _, _ = _estado(conn, position_id, "target")
    conn.close()
    assert status_tras_bajada == "first_trigger"
    assert extreme_tras_bajada == 110.0

    # Un precio más ALTO (por encima del umbral) sí debe contar.
    t2 = t1 + timedelta(hours=1)
    alert_state.record_trigger(position_id, "target", 115.0, now=t2)
    conn = get_connection()
    status_tras_subida, extreme_tras_subida, _, _ = _estado(conn, position_id, "target")
    conn.close()
    assert status_tras_subida == "new_extreme"
    assert extreme_tras_subida == 115.0


def test_periodic_reminder_fires_after_window_elapses_with_no_new_extreme(db_path):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    alert_state.record_trigger(position_id, "stop_loss", 95.0, now=t0)
    assert alert_state.should_notify(position_id, "stop_loss", now=t0) is True

    # Menos de 6 horas: no toca.
    t_antes = t0 + timedelta(hours=5)
    assert alert_state.should_notify(position_id, "stop_loss", now=t_antes) is False

    # Más de 6 horas desde la última notificación (t0), sin cambio de precio.
    t_despues = t0 + timedelta(hours=6, minutes=1)
    assert alert_state.should_notify(position_id, "stop_loss", now=t_despues) is True

    conn = get_connection()
    status, _, last_notified_at, _ = _estado(conn, position_id)
    conn.close()
    assert status == "periodic_reminder"
    assert last_notified_at is not None


def test_resolve_sets_resolved_and_next_trigger_starts_fresh_cycle(db_path):
    conn = get_connection()
    position_id = _crear_posicion(conn)
    conn.close()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=TZ_BOGOTA)
    alert_state.record_trigger(position_id, "stop_loss", 95.0, now=t0)
    alert_state.should_notify(position_id, "stop_loss", now=t0)

    alert_state.resolve(position_id, "stop_loss")

    conn = get_connection()
    status, _, _, resolved_at = _estado(conn, position_id)
    conn.close()
    assert status == "resolved"
    assert resolved_at is not None
    assert alert_state.should_notify(position_id, "stop_loss", now=t0) is False

    # Un breach nuevo empieza un first_trigger fresco, no un INSERT
    # nuevo (UNIQUE(position_id, alert_type) exige la misma fila).
    t1 = t0 + timedelta(hours=1)
    alert_state.record_trigger(position_id, "stop_loss", 90.0, now=t1)

    conn = get_connection()
    status_nuevo, extreme_nuevo, last_notified_nuevo, resolved_nuevo = _estado(conn, position_id)
    fila_count = conn.execute(
        "SELECT COUNT(*) FROM alert_state WHERE position_id = ? AND alert_type = 'stop_loss'",
        (position_id,),
    ).fetchone()[0]
    conn.close()

    assert status_nuevo == "first_trigger"
    assert extreme_nuevo == 90.0
    assert last_notified_nuevo is None
    assert resolved_nuevo is None
    assert fila_count == 1  # misma fila, no una nueva
    assert alert_state.should_notify(position_id, "stop_loss", now=t1) is True
