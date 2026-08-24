"""
Migra paper_positions (motor cripto nuevo, Fase 8) hacia el portfolio
unificado (Épica 4 de la migración de confiabilidad).

paper_positions NO se elimina ni se vacía - queda intacta como copia de
seguridad durante la ventana de coexistencia (ver blueprint §9.1), y
cada fila migrada se marca vía migrated_to_portfolio_id para que una
segunda corrida no la migre dos veces.

Un símbolo se considera "reconocido" si termina en uno de los sufijos
cripto conocidos (-USD, USDT - los mismos que
app.services.symbol_normalization sabe normalizar). Una fila con un
símbolo no reconocido se omite (no se migra), se loguea como warning, y
se reporta en el resumen final - nunca se inventa un asset_class o un
normalized_symbol para un símbolo que no se puede clasificar con
certeza.

Uso:
    python migrations/0001_portfolio_unify.py
    # exit 0 -> portfolio_despues == portfolio_antes + filas_migradas
    # exit 1 -> el conteo final no coincidió con lo esperado
"""

import sys
from pathlib import Path

# Al correr "python migrations/0001_portfolio_unify.py", Python agrega
# el directorio del script (migrations/) a sys.path, no la raíz del
# repo - por eso "import app.*" falla si no se agrega explícitamente
# (mismo fix que 0000_apply_constraints.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from app.database.connection import get_connection
from app.services.symbol_normalization import normalizar_symbol

_SUFIJOS_CRIPTO_RECONOCIDOS = ("-USD", "USDT")


def _es_symbol_reconocido(symbol: str) -> bool:
    return symbol.endswith(_SUFIJOS_CRIPTO_RECONOCIDOS)


def _migrar_una_fila(cursor, fila):
    """Inserta en portfolio la fila equivalente a esta fila de
    paper_positions. Devuelve el id insertado, o None si el símbolo no
    se reconoce (la fila se omite, no se migra)."""
    (
        _id, symbol, _direction, entry_price, stop_price, target_price,
        _size_usdt, quantity, opened_at, status, close_price, closed_at,
        _close_reason, _pnl_usdt, _pnl_pct, _scoring_id,
    ) = fila

    if not _es_symbol_reconocido(symbol):
        return None

    normalized_symbol = normalizar_symbol(symbol, "crypto")
    portfolio_status = "CLOSED" if status == "CLOSED" else "OPEN"

    cursor.execute(
        """
        INSERT INTO portfolio (
            symbol, quantity, buy_price, buy_date, target_price, stop_loss,
            status, sell_price, sell_date, asset_class, normalized_symbol,
            fees_included
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'crypto', ?, 0)
        """,
        (
            symbol, quantity, entry_price, opened_at, target_price, stop_price,
            portfolio_status, close_price, closed_at, normalized_symbol,
        ),
    )
    return cursor.lastrowid


def main() -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()

        portfolio_antes = cursor.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]

        filas_pendientes = cursor.execute(
            """
            SELECT id, symbol, direction, entry_price, stop_price, target_price,
                   size_usdt, quantity, opened_at, status, close_price, closed_at,
                   close_reason, pnl_usdt, pnl_pct, scoring_id
            FROM paper_positions
            WHERE migrated_to_portfolio_id IS NULL
            """
        ).fetchall()

        migradas = 0
        omitidas = []

        for fila in filas_pendientes:
            paper_position_id, symbol = fila[0], fila[1]
            portfolio_id = _migrar_una_fila(cursor, fila)

            if portfolio_id is None:
                logger.warning(
                    f"paper_positions.id={paper_position_id}: símbolo '{symbol}' "
                    "no reconocido, se omite (no se migra)."
                )
                omitidas.append((paper_position_id, symbol))
                continue

            cursor.execute(
                "UPDATE paper_positions SET migrated_to_portfolio_id = ? WHERE id = ?",
                (portfolio_id, paper_position_id),
            )
            migradas += 1

        conn.commit()

        portfolio_despues = cursor.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
        esperado = portfolio_antes + migradas

        print(f"portfolio antes: {portfolio_antes}")
        print(f"paper_positions pendientes de migrar: {len(filas_pendientes)}")
        print(f"filas migradas: {migradas}")
        if omitidas:
            print(f"filas omitidas (símbolo no reconocido): {omitidas}")
        print(f"portfolio después: {portfolio_despues}")

        if portfolio_despues != esperado:
            print(
                f"ERROR: se esperaban {esperado} filas en portfolio "
                f"({portfolio_antes} + {migradas} migradas), se encontraron {portfolio_despues}."
            )
            return 1

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
