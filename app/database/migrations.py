"""
Migraciones de esquema para RobotinaIA.

SQLite no soporta ALTER TABLE ... ADD CONSTRAINT: agregar CHECK o
FOREIGN KEY a una tabla que ya existe requiere el patrón de
"reconstrucción" documentado en la propia doc de SQLite - crear la
tabla nueva con las restricciones, copiar los datos, borrar la vieja,
renombrar la nueva. current_version()/apply_migrations() lo hacen
idempotente vía PRAGMA user_version, para que create_tables() se pueda
llamar cualquier cantidad de veces sin repetir trabajo.
"""


def current_version(conn) -> int:
    return conn.execute("PRAGMA user_version;").fetchone()[0]


def _set_version(conn, version: int) -> None:
    conn.execute(f"PRAGMA user_version={version};")


def _migration_001_add_constraints(conn) -> None:
    """Agrega:
      - signals.signal CHECK IN ('PENDING', 'EXECUTED', 'SOLD', 'EXPIRED')
        (el cuarto valor, EXPIRED, lo usan signal_manager.py y
        limpiar_senales_viejas.py para señales PENDING que caducaron sin
        ejecutarse - confirmado contra la base de datos real y contra
        todos los sitios del código que escriben la columna).
      - portfolio.status CHECK IN ('OPEN', 'CLOSED')
      - portfolio_decisions.position_id FOREIGN KEY -> portfolio.id

    Reconstruye las tres tablas preservando todas las filas existentes.
    """
    was_fk_on = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    conn.execute("PRAGMA foreign_keys=OFF;")
    try:
        cursor = conn.cursor()

        cursor.execute("ALTER TABLE signals RENAME TO signals_old")
        cursor.execute(
            """
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                score INTEGER NOT NULL,
                signal TEXT NOT NULL
                    CHECK (signal IN ('PENDING', 'EXECUTED', 'SOLD', 'EXPIRED')),
                price REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO signals (id, symbol, score, signal, price, timestamp)
            SELECT id, symbol, score, signal, price, timestamp FROM signals_old
            """
        )
        cursor.execute("DROP TABLE signals_old")

        cursor.execute("ALTER TABLE portfolio RENAME TO portfolio_old")
        cursor.execute(
            """
            CREATE TABLE portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                buy_price REAL NOT NULL,
                buy_date TEXT NOT NULL,
                target_price REAL,
                stop_loss REAL,
                status TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
                sell_price REAL,
                sell_date TEXT,
                alerta_stop_enviada INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO portfolio (id, symbol, quantity, buy_price, buy_date,
                target_price, stop_loss, status, sell_price, sell_date,
                alerta_stop_enviada)
            SELECT id, symbol, quantity, buy_price, buy_date,
                target_price, stop_loss, status, sell_price, sell_date,
                alerta_stop_enviada
            FROM portfolio_old
            """
        )
        cursor.execute("DROP TABLE portfolio_old")

        cursor.execute("ALTER TABLE portfolio_decisions RENAME TO portfolio_decisions_old")
        cursor.execute(
            """
            CREATE TABLE portfolio_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES portfolio(id),
                decision TEXT NOT NULL,
                precio REAL,
                timestamp TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO portfolio_decisions (id, position_id, decision, precio, timestamp)
            SELECT id, position_id, decision, precio, timestamp
            FROM portfolio_decisions_old
            """
        )
        cursor.execute("DROP TABLE portfolio_decisions_old")

        conn.commit()
    finally:
        if was_fk_on:
            conn.execute("PRAGMA foreign_keys=ON;")


def _migration_002_portfolio_asset_class(conn) -> None:
    """Agrega a portfolio: asset_class (CHECK IN ('stock', 'crypto')),
    normalized_symbol, fee_pct_applied, fees_included.

    El backfill se calcula en Python, fila por fila, en vez de con una
    expresión SQL: la clasificación cripto/acción y la normalización de
    símbolo (quitar sufijos -USD / USDT) ya viven en
    app.services.symbol_normalization / Settings.ACTIVOS_CRIPTO - una
    sola fuente de verdad, no una copia paralela en SQL. El volumen de
    filas de portfolio es pequeño (decenas, no millones), así que el
    costo de iterar en Python es irrelevante.
    """
    # Imports diferidos: evita cualquier ciclo de import a nivel de
    # módulo entre app.database.migrations y app.core/app.services.
    from app.core.settings import Settings
    from app.services.symbol_normalization import normalizar_symbol

    was_fk_on = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    conn.execute("PRAGMA foreign_keys=OFF;")
    try:
        cursor = conn.cursor()

        filas = cursor.execute(
            """
            SELECT id, symbol, quantity, buy_price, buy_date, target_price,
                   stop_loss, status, sell_price, sell_date, alerta_stop_enviada
            FROM portfolio
            """
        ).fetchall()

        # OJO: portfolio_decisions.position_id ya tiene "REFERENCES
        # portfolio(id)" desde la migración 1. Si acá renombráramos
        # "portfolio" a un nombre temporal (como hace la migración 1),
        # SQLite reescribe automáticamente esa cláusula REFERENCES en
        # portfolio_decisions para que apunte al nombre temporal - y al
        # borrar la tabla temporal, la referencia queda rota para
        # siempre. Por eso acá se construye la tabla nueva bajo un
        # nombre que NADIE referencia todavía, se borra la "portfolio"
        # original (un DROP no dispara esa reescritura), y recién al
        # final se renombra la nueva a "portfolio" - portfolio_decisions
        # nunca cambia su texto, así que la referencia sigue siendo
        # válida en cuanto ese nombre vuelve a existir.
        cursor.execute(
            """
            CREATE TABLE portfolio_new_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                buy_price REAL NOT NULL,
                buy_date TEXT NOT NULL,
                target_price REAL,
                stop_loss REAL,
                status TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
                sell_price REAL,
                sell_date TEXT,
                alerta_stop_enviada INTEGER DEFAULT 0,
                asset_class TEXT NOT NULL CHECK (asset_class IN ('stock', 'crypto')),
                normalized_symbol TEXT NOT NULL,
                fee_pct_applied REAL,
                fees_included INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        for fila in filas:
            (
                id_, symbol, quantity, buy_price, buy_date, target_price,
                stop_loss, status, sell_price, sell_date, alerta_stop_enviada,
            ) = fila

            asset_class = "crypto" if symbol in Settings.ACTIVOS_CRIPTO else "stock"
            normalized_symbol = normalizar_symbol(symbol, asset_class)

            cursor.execute(
                """
                INSERT INTO portfolio_new_v2 (
                    id, symbol, quantity, buy_price, buy_date, target_price,
                    stop_loss, status, sell_price, sell_date, alerta_stop_enviada,
                    asset_class, normalized_symbol, fee_pct_applied, fees_included
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
                """,
                (
                    id_, symbol, quantity, buy_price, buy_date, target_price,
                    stop_loss, status, sell_price, sell_date, alerta_stop_enviada,
                    asset_class, normalized_symbol,
                ),
            )

        cursor.execute("DROP TABLE portfolio")
        cursor.execute("ALTER TABLE portfolio_new_v2 RENAME TO portfolio")
        conn.commit()
    finally:
        if was_fk_on:
            conn.execute("PRAGMA foreign_keys=ON;")


# (version_objetivo, funcion) en orden. apply_migrations corre solo las
# que faltan, comparando contra PRAGMA user_version.
MIGRATIONS: list[tuple[int, callable]] = [
    (1, _migration_001_add_constraints),
    (2, _migration_002_portfolio_asset_class),
]


def apply_migrations(conn) -> None:
    version = current_version(conn)
    for target_version, migration_fn in MIGRATIONS:
        if version < target_version:
            migration_fn(conn)
            _set_version(conn, target_version)
            version = target_version
