"""
Conexión a la base de datos de RobotinaIA.
"""

import sqlite3

from app.core.settings import Settings

# Tiempo (ms) que una conexión espera antes de fallar con "database is
# locked" cuando otro hilo tiene una transacción de escritura abierta.
# Con 3 hilos (scheduler de acciones, scheduler de cripto, bot de
# Telegram) escribiendo sobre el mismo archivo SQLite, este margen evita
# que una colisión momentánea se propague como una excepción no atrapada.
BUSY_TIMEOUT_MS = 5000


def get_connection():
    """Abre una conexión SQLite con WAL, busy_timeout y foreign_keys.

    Las tres PRAGMA se aplican en cada llamada (no hay pool ni conexión
    compartida entre hilos) y ninguna falla se traga en silencio: si una
    PRAGMA no aplica correctamente, el error de sqlite3 se propaga tal
    cual, en vez de devolver una conexión a medio configurar.
    """
    conn = sqlite3.connect(Settings.DATABASE_NAME)

    journal_mode = conn.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
    if journal_mode.lower() != "wal":
        conn.close()
        raise sqlite3.OperationalError(
            f"No se pudo activar WAL, journal_mode quedó en '{journal_mode}'"
        )

    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS};")
    reported_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    if reported_timeout != BUSY_TIMEOUT_MS:
        conn.close()
        raise sqlite3.OperationalError(
            f"busy_timeout quedó en {reported_timeout}, se esperaba {BUSY_TIMEOUT_MS}"
        )

    conn.execute("PRAGMA foreign_keys=ON;")
    foreign_keys_on = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    if foreign_keys_on != 1:
        conn.close()
        raise sqlite3.OperationalError("No se pudo activar PRAGMA foreign_keys")

    return conn