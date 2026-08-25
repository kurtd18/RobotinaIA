"""
Consulta de señales para la capa de presentación (Épica 7): extrae la
consulta que app/dashboard/dashboard.py tenía embebida como SQL crudo,
para que un cambio de esquema no rompa el dashboard en silencio.

Misma consulta, mismas columnas, mismo comportamiento ante error
(DataFrame vacío) que la versión original en dashboard.py - esta tarea
es solo mover la consulta detrás de una función, no cambiar qué hace.
"""

import pandas as pd

from app.database.connection import get_connection


def listar_senales() -> pd.DataFrame:
    """Todas las señales, la más reciente primero."""
    conn = get_connection()

    try:
        df = pd.read_sql_query(
            """
            SELECT
                id,
                symbol,
                score,
                signal,
                price,
                timestamp
            FROM signals
            ORDER BY id DESC
            """,
            conn,
        )
    except Exception:
        df = pd.DataFrame()

    conn.close()

    return df
