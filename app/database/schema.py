"""
Definición del esquema de base de datos de RobotinaIA.

Fuente única de verdad para el DDL de todas las tablas. scheduler_runs
y paper_positions vivían como constantes propias en
app/scheduler/repository.py y app/paper_trading/repository.py; ahora
se definen aquí y esos módulos importan la constante en vez de
mantener su propia copia (sus funciones crear_tabla() siguen abriendo
su propia conexión, sin cambios, para no romper los tests que
monkeypatchean repository.get_connection directamente).

stock_scheduler_runs y alert_state son esquema inicial para las
Épicas 6 y 5 de la migración de confiabilidad - todavía sin código que
las use.
"""

from .connection import get_connection
from .migrations import apply_migrations

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

# Esta es la forma "base" de portfolio, previa a las migraciones. Las
# columnas asset_class/normalized_symbol/fee_pct_applied/fees_included
# (Épica 4, unificación de portfolio) se agregan vía
# app.database.migrations._migration_002_portfolio_asset_class, no
# acá - misma razón que el CHECK de status: SQLite no permite agregar
# CHECK ni columnas NOT NULL calculadas por fila con ALTER TABLE, así
# que el camino único hacia el esquema final es la migración versionada,
# tanto para bases nuevas como viejas.
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

# Movida desde app/scheduler/repository.py (Fase 10) - misma definición,
# ahora con esta como única fuente de verdad.
SCHEMA_SCHEDULER_RUNS = """
CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora_programada TEXT NOT NULL,
    ejecutado_en TEXT NOT NULL,
    UNIQUE(fecha, hora_programada)
)
"""

# Movida desde app/paper_trading/repository.py (Fase 8) - misma
# definición, ahora con esta como única fuente de verdad.
SCHEMA_PAPER_POSITIONS = """
CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    size_usdt REAL NOT NULL,
    quantity REAL NOT NULL,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    close_price REAL,
    closed_at TEXT,
    close_reason TEXT,
    pnl_usdt REAL,
    pnl_pct REAL,
    scoring_id INTEGER
)
"""

# Esquema inicial para Épica 6 (supervisor del scheduler de acciones,
# idempotencia). Mismo patrón que scheduler_runs (cripto). Si Épica 6
# necesita columnas adicionales, se agregan vía una migración nueva en
# migrations.py, no editando esta constante.
SCHEMA_STOCK_SCHEDULER_RUNS = """
CREATE TABLE IF NOT EXISTS stock_scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora_programada TEXT NOT NULL,
    ejecutado_en TEXT NOT NULL,
    UNIQUE(fecha, hora_programada)
)
"""

# Esta es la forma "base" de alert_state, previa a la migración 3. El
# CHECK sobre status, el UNIQUE(position_id, alert_type) y la FK a
# portfolio(id) se agregan vía
# app.database.migrations._migration_003_alert_state_constraints, no
# acá - misma razón que portfolio: SQLite no permite agregar CHECK ni
# UNIQUE con ALTER TABLE.
SCHEMA_ALERT_STATE = """
CREATE TABLE IF NOT EXISTS alert_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'first_trigger',
    extreme_price REAL,
    first_triggered_at TEXT NOT NULL,
    last_notified_at TEXT,
    resolved_at TEXT
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
    cursor.execute(SCHEMA_SCHEDULER_RUNS)
    cursor.execute(SCHEMA_PAPER_POSITIONS)
    cursor.execute(SCHEMA_STOCK_SCHEDULER_RUNS)
    cursor.execute(SCHEMA_ALERT_STATE)

    _agregar_columna_si_no_existe(cursor, "portfolio", "alerta_stop_enviada", "INTEGER DEFAULT 0")
    # Épica 4 (unificación de portfolio): marca qué filas de
    # paper_positions ya se migraron a portfolio, para que
    # migrations/0001_portfolio_unify.py sea idempotente. Nullable, sin
    # rebuild necesario - additivo como alerta_stop_enviada arriba.
    _agregar_columna_si_no_existe(cursor, "paper_positions", "migrated_to_portfolio_id", "INTEGER")

    conn.commit()

    apply_migrations(conn)

    conn.close()