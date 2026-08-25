"""
Máquina de estados de alertas persistida (Épica 5): first_trigger /
periodic_reminder / new_extreme / resolved - para que un stop-loss o
target sin resolver no se notifique una sola vez y nunca más. Ese era
exactamente el bug que dejó la posición BTC-USD estancada
indefinidamente (Épica 12 del backlog): la alerta se disparaba una vez
y, si nadie respondía, no volvía a avisar hasta que el precio se
recuperara por encima del stop.

Ciclo de vida para un (position_id, alert_type):
  - record_trigger(): primera vez para ese par -> status='first_trigger'.
    Si ya existía y el precio empeora más de
    Settings.ALERTA_CAMBIO_MATERIAL_PCT respecto al extremo ya
    registrado -> status='new_extreme'. Si no hay cambio material, no
    toca nada (status y last_notified_at quedan como estaban).
  - should_notify(): True si el evento actual (first_trigger o
    new_extreme) todavía no se notificó (last_notified_at es NULL), o
    si ya pasaron Settings.ALERTA_RECORDATORIO_HORAS desde la última
    notificación (transicionando a periodic_reminder en ese momento).
    False en cualquier otro caso, y siempre False si está resolved.
  - resolve(): marca resolved. El siguiente record_trigger para el
    mismo (position_id, alert_type) actualiza la misma fila de vuelta a
    first_trigger (no inserta una fila nueva - UNIQUE(position_id,
    alert_type) lo exige).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.settings import Settings
from app.database.connection import get_connection

TZ_BOGOTA = ZoneInfo("America/Bogota")
_FORMATO_TIMESTAMP = "%Y-%m-%d %H:%M:%S%z"


def _ahora() -> datetime:
    return datetime.now(TZ_BOGOTA)


def _a_texto(momento: datetime) -> str:
    return momento.strftime(_FORMATO_TIMESTAMP)


def _desde_texto(texto: str) -> datetime:
    return datetime.strptime(texto, _FORMATO_TIMESTAMP)


def _es_cambio_material(alert_type: str, price: float, extreme_price: float) -> bool:
    """True si `price` es más extremo que `extreme_price` en la
    dirección que importa para `alert_type`, por más del umbral
    Settings.ALERTA_CAMBIO_MATERIAL_PCT.

    stop_loss: el extremo registrado es el precio más BAJO visto (una
    caída mayor es lo que importa). target: el extremo es el precio más
    ALTO visto (una subida mayor es lo que importa). La dirección se
    invierte fácil por error - de ahí el nombre explícito en vez de un
    "mayor variación" genérico.
    """
    if alert_type == "stop_loss":
        mas_extremo = price < extreme_price
    else:
        mas_extremo = price > extreme_price

    if not mas_extremo:
        return False

    if extreme_price == 0:
        return True

    variacion_pct = abs(price - extreme_price) / abs(extreme_price) * 100
    return variacion_pct > Settings.ALERTA_CAMBIO_MATERIAL_PCT


def record_trigger(position_id: int, alert_type: str, price: float, now: datetime = None) -> None:
    momento = now or _ahora()
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT id, status, extreme_price FROM alert_state "
            "WHERE position_id = ? AND alert_type = ?",
            (position_id, alert_type),
        ).fetchone()

        if fila is None:
            conn.execute(
                """
                INSERT INTO alert_state (
                    position_id, alert_type, status, extreme_price,
                    first_triggered_at, last_notified_at, resolved_at
                ) VALUES (?, ?, 'first_trigger', ?, ?, NULL, NULL)
                """,
                (position_id, alert_type, price, _a_texto(momento)),
            )
            conn.commit()
            return

        alert_id, status, extreme_price = fila

        if status == "resolved":
            conn.execute(
                """
                UPDATE alert_state
                SET status = 'first_trigger', extreme_price = ?,
                    first_triggered_at = ?, last_notified_at = NULL, resolved_at = NULL
                WHERE id = ?
                """,
                (price, _a_texto(momento), alert_id),
            )
            conn.commit()
            return

        if _es_cambio_material(alert_type, price, extreme_price):
            conn.execute(
                "UPDATE alert_state SET status = 'new_extreme', extreme_price = ?, "
                "last_notified_at = NULL WHERE id = ?",
                (price, alert_id),
            )
            conn.commit()
    finally:
        conn.close()


def should_notify(position_id: int, alert_type: str, now: datetime = None) -> bool:
    momento = now or _ahora()
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT id, status, last_notified_at FROM alert_state "
            "WHERE position_id = ? AND alert_type = ?",
            (position_id, alert_type),
        ).fetchone()

        if fila is None:
            return False

        alert_id, status, last_notified_at = fila

        if status == "resolved":
            return False

        if last_notified_at is None:
            # first_trigger o new_extreme recién registrados, todavía no
            # notificados - notificar ahora y marcarlo.
            conn.execute(
                "UPDATE alert_state SET last_notified_at = ? WHERE id = ?",
                (_a_texto(momento), alert_id),
            )
            conn.commit()
            return True

        horas_transcurridas = (momento - _desde_texto(last_notified_at)).total_seconds() / 3600
        if horas_transcurridas >= Settings.ALERTA_RECORDATORIO_HORAS:
            conn.execute(
                "UPDATE alert_state SET status = 'periodic_reminder', last_notified_at = ? "
                "WHERE id = ?",
                (_a_texto(momento), alert_id),
            )
            conn.commit()
            return True

        return False
    finally:
        conn.close()


def resolve(position_id: int, alert_type: str) -> None:
    momento = _ahora()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE alert_state SET status = 'resolved', resolved_at = ? "
            "WHERE position_id = ? AND alert_type = ?",
            (_a_texto(momento), position_id, alert_type),
        )
        conn.commit()
    finally:
        conn.close()
