"""
Gestión de señales: consulta de pendientes, marcado manual y
expiración automática de señales que llevan mucho tiempo pendientes.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from app.database.connection import get_connection

SIGNAL_EXPIRATION_MINUTES = 15
TZ_BOGOTA = ZoneInfo("America/Bogota")


def show_pending_signals():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, symbol, score, price, timestamp
        FROM signals
        WHERE signal='PENDING'
        ORDER BY id DESC
        """
    )

    rows = cursor.fetchall()
    conn.close()

    logger.info("SEÑALES PENDIENTES")

    if not rows:
        logger.info("No existen señales pendientes.")
        return

    for signal_id, symbol, score, price, timestamp in rows:
        logger.info(
            f"ID: {signal_id} | Activo: {symbol} | Score: {score} "
            f"| Precio: {price} | Fecha: {timestamp}"
        )


def mark_as_executed(signal_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE signals SET signal='EXECUTED' WHERE id=?",
        (signal_id,),
    )

    conn.commit()
    conn.close()

    logger.info(f"Señal {signal_id} marcada como EXECUTED.")


def mark_as_expired(signal_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE signals SET signal='EXPIRED' WHERE id=?",
        (signal_id,),
    )

    conn.commit()
    conn.close()

    logger.info(f"Señal {signal_id} marcada como EXPIRED.")


TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_timestamp(timestamp: str):
    """Parsea el timestamp guardado por scoring.py (con o sin offset de zona horaria).

    Usa strptime en vez de fromisoformat porque fromisoformat cambió su
    comportamiento entre versiones de Python (mucho más estricto antes de 3.11),
    y strptime con %z es consistente desde Python 3.7.
    """

    for fmt in TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(timestamp, fmt)
            break
        except ValueError:
            continue
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BOGOTA)

    return dt


def expire_old_signals():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, timestamp FROM signals WHERE signal='PENDING'")
    rows = cursor.fetchall()

    expired = 0

    for signal_id, timestamp in rows:
        created_at = _parse_timestamp(timestamp)

        if created_at is None:
            logger.warning(f"Señal {signal_id}: timestamp inválido ({timestamp}), se ignora")
            continue

        if datetime.now(TZ_BOGOTA) - created_at > timedelta(minutes=SIGNAL_EXPIRATION_MINUTES):
            cursor.execute(
                "UPDATE signals SET signal='EXPIRED' WHERE id=?",
                (signal_id,),
            )
            expired += 1

    conn.commit()
    conn.close()

    logger.info(f"Señales expiradas: {expired}")


def _menu():
    print("\nROBOTINAIA SIGNAL MANAGER V1")
    print("\n1. Mostrar pendientes")
    print("2. Expirar señales")

    option = input("\nSeleccione una opción: ")

    if option == "1":
        show_pending_signals()
    elif option == "2":
        expire_old_signals()
    else:
        print("Opción inválida.")


if __name__ == "__main__":
    _menu()