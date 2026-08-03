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


def obtener_senal_pendiente_por_symbol(symbol):
    """Devuelve (id, price) de la señal PENDING de ese símbolo, o None si
    no hay ninguna abierta. A diferencia de existe_senal_pendiente (que
    solo dice sí/no), esta devuelve el precio de entrada - necesario para
    calcular el resultado (% de ganancia o pérdida) cuando se cierra la
    posición."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, price
        FROM signals
        WHERE symbol = ?
        AND signal = 'PENDING'
        ORDER BY id DESC
        LIMIT 1
        """,
        (symbol,),
    )

    result = cursor.fetchone()

    conn.close()

    return result


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


def marcar_senal_vendida(signal_id):
    """Marca una señal como cerrada (vendida) - se usa cuando se cumple
    la condición de salida del RSI(2) de Connors (RSI cruza sobre 70, o
    el precio cae bajo la SMA de tendencia)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE signals SET signal='SOLD' WHERE id=?",
        (signal_id,),
    )

    conn.commit()
    conn.close()


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