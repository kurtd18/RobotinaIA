import sqlite3

DB_NAME = "robotinaia.db"


def get_connection():

    return sqlite3.connect(
        DB_NAME
    )


# ===================================================
# SIGNALS
# ===================================================

def guardar_senal(
    timestamp,
    symbol,
    score,
    price
):

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
            timestamp
        )
    )

    conn.commit()
    conn.close()

    print(
        f"Señal almacenada: {symbol}"
    )


def existe_senal_pendiente(
    symbol
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id

        FROM signals

        WHERE symbol=?
        AND signal='PENDING'
        """,
        (symbol,)
    )

    result = cursor.fetchone()

    conn.close()

    return result is not None


# ===================================================
# UTILIDADES
# ===================================================

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

    print(
        cursor.fetchall()
    )

    conn.close()


if __name__ == "__main__":

    show_tables()