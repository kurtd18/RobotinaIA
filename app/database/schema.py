"""
Definición del esquema de base de datos de RobotinaIA.
"""

from .connection import get_connection

SCHEMA_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    score INTEGER NOT NULL,
    signal TEXT NOT NULL,
    price REAL NOT NULL,
    timestamp TEXT NOT NULL
)
"""

SCHEMA_PORTFOLIO = """
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    buy_price REAL NOT NULL,
    buy_date TEXT NOT NULL,
    target_price REAL,
    stop_loss REAL,
    status TEXT DEFAULT 'OPEN',
    sell_price REAL,
    sell_date TEXT,
    alerta_stop_enviada INTEGER DEFAULT 0
)
"""

SCHEMA_STATS = """
CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_signals INTEGER,
    buy_signals INTEGER,
    sell_signals INTEGER,
    updated_at TEXT
)
"""

SCHEMA_PORTFOLIO_DECISIONS = """
CREATE TABLE IF NOT EXISTS portfolio_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    precio REAL,
    timestamp TEXT NOT NULL
)
"""


def _agregar_columna_si_no_existe(cursor, tabla, columna, definicion):
    """Agrega una columna a una tabla existente si todavía no la tiene.

    Necesario porque bases de datos creadas antes de agregar esta columna
    al esquema no la reciben automáticamente con CREATE TABLE IF NOT EXISTS
    (eso solo aplica si la tabla no existía). No usamos Alembic todavía
    (ver BACKLOG Épica 8), así que este es el mecanismo simple mientras tanto.
    """

    cursor.execute(f"PRAGMA table_info({tabla})")
    columnas_existentes = [fila[1] for fila in cursor.fetchall()]

    if columna not in columnas_existentes:
        cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")


def create_tables():
    """Crea todas las tablas necesarias si no existen, y agrega columnas nuevas
    a tablas que ya existían con un esquema anterior."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(SCHEMA_SIGNALS)
    cursor.execute(SCHEMA_PORTFOLIO)
    cursor.execute(SCHEMA_STATS)
    cursor.execute(SCHEMA_PORTFOLIO_DECISIONS)

    _agregar_columna_si_no_existe(cursor, "portfolio", "alerta_stop_enviada", "INTEGER DEFAULT 0")

    conn.commit()
    conn.close()