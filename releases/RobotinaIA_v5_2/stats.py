import sqlite3

conn = sqlite3.connect(
    "signals.db"
)

cursor = conn.cursor()

print("=" * 80)
print("ESTADISTICAS ROBOTINAIA")
print("=" * 80)

# Totales
cursor.execute(
    "SELECT COUNT(*) FROM signals"
)

total = cursor.fetchone()[0]

# Ganadas
cursor.execute(
    """
    SELECT COUNT(*)
    FROM signals
    WHERE resultado='GANO'
    """
)

gano = cursor.fetchone()[0]

# Perdidas
cursor.execute(
    """
    SELECT COUNT(*)
    FROM signals
    WHERE resultado='PERDIO'
    """
)

perdio = cursor.fetchone()[0]

# Pendientes
cursor.execute(
    """
    SELECT COUNT(*)
    FROM signals
    WHERE resultado='PENDIENTE'
    """
)

pendiente = cursor.fetchone()[0]

# Win Rate
if (gano + perdio) > 0:

    win_rate = (
        gano /
        (gano + perdio)
    ) * 100

else:

    win_rate = 0

print(f"Total señales : {total}")
print(f"Ganadas       : {gano}")
print(f"Perdidas      : {perdio}")
print(f"Pendientes    : {pendiente}")
print(f"Win Rate      : {win_rate:.2f}%")

print()
print("=" * 80)
print("TOP ACTIVOS")
print("=" * 80)

cursor.execute(
    """
    SELECT
        activo,
        COUNT(*)
    FROM signals
    GROUP BY activo
    ORDER BY COUNT(*) DESC
    """
)

for fila in cursor.fetchall():

    print(
        f"{fila[0]:15} {fila[1]}"
    )

print()
print("=" * 80)
print("ULTIMAS 10 SENALES")
print("=" * 80)

cursor.execute(
    """
    SELECT
        fecha,
        activo,
        score,
        resultado
    FROM signals

    ORDER BY id DESC

    LIMIT 10
    """
)

for fila in cursor.fetchall():

    print(
        fila
    )

print("=" * 80)

conn.close()