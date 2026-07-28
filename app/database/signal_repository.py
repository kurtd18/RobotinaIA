from .connection import get_connection


def guardar_senal(timestamp, symbol, score, price):
    """Guarda una señal nueva y devuelve su ID."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO signals (
            symbol,
            score,
            signal,
            price,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            symbol,
            score,
            "PENDING",
            price,
            timestamp,
        ),
    )

    signal_id = cursor.lastrowid

    conn.commit()
    conn.close()

    print(f"Señal almacenada: {symbol} (ID {signal_id})")

    return signal_id


def existe_senal_pendiente(symbol):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM signals
        WHERE symbol = ?
        AND signal = 'PENDING'
        """,
        (symbol,),
    )

    result = cursor.fetchone()

    conn.close()

    return result is not None


def obtener_senal(signal_id):
    """Devuelve (symbol, price) de una señal por su ID, o None si no existe."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT symbol, price
        FROM signals
        WHERE id = ?
        """,
        (signal_id,),
    )

    result = cursor.fetchone()

    conn.close()

    return result


def show_tables():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        """
    )

    print(cursor.fetchall())

    conn.close()