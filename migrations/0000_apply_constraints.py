"""
Aplica las migraciones de esquema (ver app/database/migrations.py)
contra la base de datos configurada (Settings.DATABASE_NAME), con
verificación de conteo de filas antes/después y una validación
explícita de huérfanos antes de tocar nada.

La migración en sí (app/database/migrations.py) apaga
PRAGMA foreign_keys durante la reconstrucción de las tablas, así que
una fila huérfana en portfolio_decisions se copiaría sin quejarse. Por
eso este script la busca ANTES de aplicar nada y aborta si encuentra
alguna - la corrección de datos huérfanos es una decisión del operador,
no algo que este script deba resolver solo.

Uso:
    python migrations/0000_apply_constraints.py
    # exit 0 -> migración aplicada (o ya lo estaba), conteos de filas
    #           idénticos antes/después, por tabla
    # exit 1 -> se encontró una fila huérfana en
    #           portfolio_decisions.position_id antes de aplicar nada
    #           (no se tocó la base de datos), o los conteos no
    #           coincidieron después de migrar
"""

import sys
from pathlib import Path

# Al correr "python migrations/0000_apply_constraints.py", Python agrega
# el directorio del script (migrations/) a sys.path, no la raíz del
# repo - por eso "import app.*" falla si no se agrega explícitamente.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.connection import get_connection
from app.database.migrations import apply_migrations, current_version


def _tablas(conn):
    return [
        fila[0]
        for fila in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name != 'sqlite_sequence';"
        ).fetchall()
    ]


def _conteos(conn, tablas):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tablas}


def _huerfanos_portfolio_decisions(conn):
    """Filas de portfolio_decisions cuyo position_id no existe en
    portfolio. Devuelve [] si alguna de las dos tablas todavía no
    existe (base de datos nueva, nada que revisar todavía)."""
    tablas = set(_tablas(conn))
    if "portfolio_decisions" not in tablas or "portfolio" not in tablas:
        return []
    return conn.execute(
        """
        SELECT pd.id, pd.position_id
        FROM portfolio_decisions pd
        LEFT JOIN portfolio p ON p.id = pd.position_id
        WHERE p.id IS NULL
        """
    ).fetchall()


def main() -> int:
    conn = get_connection()
    try:
        huerfanos = _huerfanos_portfolio_decisions(conn)
        if huerfanos:
            print(
                "Se encontraron filas huérfanas en portfolio_decisions "
                "(position_id sin fila correspondiente en portfolio):"
            )
            for id_, position_id in huerfanos:
                print(f"  portfolio_decisions.id={id_} -> position_id={position_id} (no existe)")
            print("No se aplicó ninguna migración. Resuelva estas filas primero.")
            return 1

        tablas = _tablas(conn)
        conteos_antes = _conteos(conn, tablas)
        version_antes = current_version(conn)

        apply_migrations(conn)

        conteos_despues = _conteos(conn, tablas)
        version_despues = current_version(conn)

        if conteos_antes != conteos_despues:
            print("ERROR: los conteos de filas no coinciden antes/después de migrar.")
            print("antes:  ", conteos_antes)
            print("después:", conteos_despues)
            return 1

        if version_antes == version_despues:
            print(f"Ya estaba en la versión {version_despues}; nada que migrar.")
        else:
            print(f"Migrado de la versión {version_antes} a la versión {version_despues}.")
        print("Conteos de filas idénticos por tabla:", conteos_despues)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
