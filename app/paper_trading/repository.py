"""
Persistencia de posiciones de paper trading en SQLite.

Tabla propia (paper_positions), separada de las tablas de la estrategia
de acciones y de crypto_scores (Fase 7), en la misma base de datos
(reutiliza app/database/connection.py sin modificarlo).

100% simulado: no hay ninguna conexión a un exchange ni ejecución real
de órdenes en ningún punto de este módulo.
"""

from datetime import datetime

from app.database.connection import get_connection
from app.database.schema import SCHEMA_PAPER_POSITIONS


def crear_tabla():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(SCHEMA_PAPER_POSITIONS)
    conn.commit()
    conn.close()


def guardar_posicion_abierta(posicion: dict) -> int:
    crear_tabla()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO paper_positions (
            symbol, direction, entry_price, stop_price, target_price,
            size_usdt, quantity, opened_at, status, scoring_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
        """,
        (
            posicion["symbol"], posicion["direction"], posicion["entry_price"],
            posicion["stop_price"], posicion["target_price"], posicion["size_usdt"],
            posicion["quantity"],
            posicion["opened_at"].isoformat() if isinstance(posicion["opened_at"], datetime)
            else posicion["opened_at"],
            posicion.get("scoring_id"),
        ),
    )
    conn.commit()
    id_insertado = cursor.lastrowid
    conn.close()
    return id_insertado


def obtener_posiciones_abiertas(symbol: str) -> list[dict]:
    crear_tabla()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, symbol, direction, entry_price, stop_price, target_price,
               size_usdt, quantity, opened_at
        FROM paper_positions
        WHERE symbol = ? AND status = 'OPEN'
        ORDER BY id ASC
        """,
        (symbol,),
    )
    filas = cursor.fetchall()
    conn.close()

    return [
        {
            "id": f[0], "symbol": f[1], "direction": f[2], "entry_price": f[3],
            "stop_price": f[4], "target_price": f[5], "size_usdt": f[6],
            "quantity": f[7], "opened_at": f[8],
        }
        for f in filas
    ]


def cerrar_posicion(position_id: int, close_price: float, close_reason: str,
                     pnl_usdt: float, pnl_pct: float, closed_at: datetime):
    crear_tabla()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE paper_positions
        SET status = 'CLOSED', close_price = ?, closed_at = ?, close_reason = ?,
            pnl_usdt = ?, pnl_pct = ?
        WHERE id = ?
        """,
        (close_price, closed_at.isoformat(), close_reason, pnl_usdt, pnl_pct, position_id),
    )
    conn.commit()
    conn.close()


def obtener_historial(symbol: str = None) -> list[dict]:
    """Todas las posiciones (abiertas y cerradas), la más reciente primero."""
    crear_tabla()
    conn = get_connection()
    cursor = conn.cursor()

    if symbol:
        cursor.execute(
            "SELECT * FROM paper_positions WHERE symbol = ? ORDER BY id DESC", (symbol,)
        )
    else:
        cursor.execute("SELECT * FROM paper_positions ORDER BY id DESC")

    columnas = [d[0] for d in cursor.description]
    filas = cursor.fetchall()
    conn.close()

    return [dict(zip(columnas, f)) for f in filas]
