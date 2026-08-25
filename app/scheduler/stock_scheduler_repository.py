"""
Registro de ejecuciones del scheduler de acciones, para idempotencia
(Épica 6). Tabla propia (stock_scheduler_runs, definida en Épica 2),
separada de scheduler_runs (cripto) - las ventanas de acciones y cripto
nunca deben colisionar sobre la misma restricción UNIQUE(fecha,
hora_programada).

Puerto 1:1 de app/scheduler/repository.py.intentar_registrar_ejecucion,
mismo shape, misma tabla en la misma base de datos (reutiliza
app/database/connection.py sin modificarlo).
"""

import sqlite3
from datetime import datetime, timezone

from app.database.connection import get_connection
from app.database.schema import SCHEMA_STOCK_SCHEDULER_RUNS


def crear_tabla():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(SCHEMA_STOCK_SCHEDULER_RUNS)
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
            "INSERT INTO stock_scheduler_runs (fecha, hora_programada, ejecutado_en) "
            "VALUES (?, ?, ?)",
            (fecha, hora_programada, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()
