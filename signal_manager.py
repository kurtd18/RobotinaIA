import sqlite3
from datetime import datetime, timedelta

DB_NAME = "robotinaia.db"


def get_connection():

    return sqlite3.connect(
        DB_NAME
    )


def show_pending_signals():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            symbol,
            score,
            price,
            timestamp
        FROM signals
        WHERE signal='PENDING'
        ORDER BY id DESC
        """
    )

    rows = cursor.fetchall()

    conn.close()

    print("\nSEÑALES PENDIENTES")
    print("=" * 50)

    if not rows:

        print("No existen señales pendientes.")
        return

    for row in rows:

        (
            signal_id,
            symbol,
            score,
            price,
            timestamp
        ) = row

        print(
            f"ID: {signal_id}"
        )

        print(
            f"Activo: {symbol}"
        )

        print(
            f"Score: {score}"
        )

        print(
            f"Precio: {price}"
        )

        print(
            f"Fecha: {timestamp}"
        )

        print(
            "-" * 50
        )


def mark_as_executed(
    signal_id
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE signals
        SET signal='EXECUTED'
        WHERE id=?
        """,
        (signal_id,)
    )

    conn.commit()
    conn.close()

    print(
        f"Señal {signal_id} marcada como EXECUTED."
    )


def mark_as_expired(
    signal_id
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE signals
        SET signal='EXPIRED'
        WHERE id=?
        """,
        (signal_id,)
    )

    conn.commit()
    conn.close()

    print(
        f"Señal {signal_id} marcada como EXPIRED."
    )


def expire_old_signals():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            timestamp
        FROM signals
        WHERE signal='PENDING'
        """
    )

    rows = cursor.fetchall()

    expired = 0

    for signal_id, timestamp in rows:

        try:

            created_at = datetime.strptime(
                timestamp,
                "%Y-%m-%d %H:%M:%S.%f"
            )

        except:

            try:

                created_at = datetime.strptime(
                    timestamp,
                    "%Y-%m-%d %H:%M:%S"
                )

            except:

                continue

        if (
            datetime.now()
            - created_at
        ) > timedelta(
            minutes=15
        ):

            cursor.execute(
                """
                UPDATE signals
                SET signal='EXPIRED'
                WHERE id=?
                """,
                (signal_id,)
            )

            expired += 1

    conn.commit()
    conn.close()

    print(
        f"Señales expiradas: {expired}"
    )


if __name__ == "__main__":

    print(
        "\nROBOTINAIA SIGNAL MANAGER V1"
    )

    print(
        "\n1. Mostrar pendientes"
    )

    print(
        "2. Expirar señales"
    )

    option = input(
        "\nSeleccione una opción: "
    )

    if option == "1":

        show_pending_signals()

    elif option == "2":

        expire_old_signals()

    else:

        print(
            "Opción inválida."
        )