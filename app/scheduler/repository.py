"""
Registro de ejecuciones del scheduler crypto, para idempotencia (Fase
10). Tabla propia (scheduler_runs), misma base de datos, reutiliza
app/database/connection.py sin modificarlo.

Una fila por ventana (fecha + hora programada, ej. "2026-08-12"+"06:00").
La restricción UNIQUE(fecha, hora_programada) es lo que impide correr
dos veces el mismo análisis si el proceso se reinicia o el disparador
se activa duplicado dentro de la misma ventana.
"""

import sqlite3
from datetime import datetime, timezone

from app.database.connection import get_connection

SCHEMA_SCHEDULER_RUNS = """
CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora_programada TEXT NOT NULL,
    ejecutado_en TEXT NOT NULL,
    UNIQUE(fecha, hora_programada)
)
"""


def crear_tabla():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(SCHEMA_SCHEDULER_RUNS)
    conn.commit()
    conn.close()


def intentar_registrar_ejecucion(fecha: str, hora_programada: str) -> bool:
    """
    Intenta reservar la ventana (fecha, hora_programada). Devuelve True
    si logró reservarla (nadie la había ejecutado todavía - se debe
    correr el análisis), o False si ya existía (ya se ejecutó esa
    ventana - se debe saltar, es un duplicado).
    """
    crear_tabla()
    conn = get_connection()

    try:
        conn.execute(
            "INSERT INTO scheduler_runs (fecha, hora_programada, ejecutado_en) VALUES (?, ?, ?)",
            (fecha, hora_programada, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()
