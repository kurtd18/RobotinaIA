import sqlite3


def guardar_senal(
    fecha,
    activo,
    score,
    precio
):

    conn = sqlite3.connect(
        "signals.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO signals(

            fecha,
            activo,
            score,
            precio_entrada,
            resultado

        )

        VALUES(

            ?,
            ?,
            ?,
            ?,
            ?

        )
        """,
        (
            fecha,
            activo,
            score,
            precio,
            "PENDIENTE"
        )
    )

    conn.commit()

    conn.close()


def existe_senal_pendiente(
    activo
):

    conn = sqlite3.connect(
        "signals.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)

        FROM signals

        WHERE
            activo=?
            AND resultado='PENDIENTE'
        """,
        (
            activo,
        )
    )

    cantidad = cursor.fetchone()[0]

    conn.close()

    return cantidad > 0


def total_senales():

    conn = sqlite3.connect(
        "signals.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM signals
        """
    )

    total = cursor.fetchone()[0]

    conn.close()

    return total


def total_ganadas():

    conn = sqlite3.connect(
        "signals.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)

        FROM signals

        WHERE resultado='GANO'
        """
    )

    total = cursor.fetchone()[0]

    conn.close()

    return total


def total_perdidas():

    conn = sqlite3.connect(
        "signals.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)

        FROM signals

        WHERE resultado='PERDIO'
        """
    )

    total = cursor.fetchone()[0]

    conn.close()

    return total