"""
Estadísticas de señales de RobotinaIA.

Nota: esto refleja el estado actual del esquema (PENDING/EXECUTED/EXPIRED).
Todavía no existe una relación entre una señal y la posición de portafolio
que generó, así que no se puede calcular ganó/perdió real por señal.
Eso queda anotado en el backlog como una funcionalidad futura.
"""

from app.database.connection import get_connection


def obtener_conteo_por_estado():
    """Cuenta señales por estado: PENDING, EXECUTED, EXPIRED."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM signals")
    total = cursor.fetchone()[0]

    conteos = {}
    for estado in ("PENDING", "EXECUTED", "EXPIRED"):
        cursor.execute(
            "SELECT COUNT(*) FROM signals WHERE signal = ?",
            (estado,),
        )
        conteos[estado] = cursor.fetchone()[0]

    conn.close()

    return total, conteos


def obtener_top_activos():
    """Cuenta señales agrupadas por símbolo, de mayor a menor."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT symbol, COUNT(*)
        FROM signals
        GROUP BY symbol
        ORDER BY COUNT(*) DESC
        """
    )

    filas = cursor.fetchall()
    conn.close()

    return filas


def obtener_ultimas_senales(limite=10):
    """Devuelve las últimas N señales registradas."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT timestamp, symbol, score, signal
        FROM signals
        ORDER BY id DESC
        LIMIT ?
        """,
        (limite,),
    )

    filas = cursor.fetchall()
    conn.close()

    return filas


def mostrar_estadisticas():
    """Imprime en consola un resumen de estadísticas de señales."""

    print("=" * 80)
    print("ESTADISTICAS ROBOTINAIA")
    print("=" * 80)

    total, conteos = obtener_conteo_por_estado()

    print(f"Total señales : {total}")
    print(f"Pendientes    : {conteos['PENDING']}")
    print(f"Ejecutadas    : {conteos['EXECUTED']}")
    print(f"Expiradas     : {conteos['EXPIRED']}")

    print()
    print("=" * 80)
    print("TOP ACTIVOS")
    print("=" * 80)

    for symbol, cantidad in obtener_top_activos():
        print(f"{symbol:15} {cantidad}")

    print()
    print("=" * 80)
    print("ULTIMAS 10 SENALES")
    print("=" * 80)

    for fila in obtener_ultimas_senales():
        print(fila)

    print("=" * 80)


if __name__ == "__main__":
    mostrar_estadisticas()