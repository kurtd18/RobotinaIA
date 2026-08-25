"""
Herramienta operador-driven para resolver la posición BTC-USD estancada
(portfolio.id=2 en la base real - Épica 12 del backlog). La auditoría
encontró la causa: la alerta de stop-loss se dispara una sola vez
(antes de Épica 5) y nadie respondió, así que quedó abierta
indefinidamente.

Cerrar o migrar una posición real es una decisión financiera, nunca
algo que el código deba tomar solo - por eso este script exige
--action explícito (sin default) y, para cerrar, --confirm-close
además. Sin esos flags, no toca la base de datos.

Modos:
  --action=migrate
      Deja la posición OPEN, confirma/asigna asset_class='crypto' y
      normalized_symbol='BTC' (la migración de Epic 4 ya lo hizo para
      la posición real - este modo es idempotente, no falla si ya
      estaba unificada).
  --action=close --confirm-close
      Pide el precio actual a YahooProvider y cierra la posición vía
      portfolio_service.sell_position.

Uso:
    python migrations/0002_resolve_stale_btc.py
    # (sin flags) -> imprime ambas opciones, exit 2, no toca la DB

    python migrations/0002_resolve_stale_btc.py --action=migrate
    # exit 0 -> posición OPEN, asset_class/normalized_symbol confirmados

    python migrations/0002_resolve_stale_btc.py --action=close
    # exit 2 -> falta --confirm-close, no toca la DB

    python migrations/0002_resolve_stale_btc.py --action=close --confirm-close
    # exit 0 -> posición CLOSED, sell_price real de YahooProvider
"""

import argparse
import sys
from pathlib import Path

# Al correr "python migrations/0002_resolve_stale_btc.py", Python agrega
# el directorio del script a sys.path, no la raíz del repo - mismo fix
# que 0000_apply_constraints.py y 0001_portfolio_unify.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.connection import get_connection
from app.providers.yahoo_provider import YahooProvider
from app.services import portfolio_service
from app.services.symbol_normalization import normalizar_symbol

STALE_BTC_POSITION_ID = 2
STALE_BTC_SYMBOL = "BTC-USD"


def _imprimir_opciones() -> None:
    print(
        "Se requiere --action=migrate o --action=close.\n\n"
        "  --action=migrate\n"
        "      Deja la posición abierta (status OPEN), confirma/asigna\n"
        "      asset_class='crypto' y normalized_symbol='BTC'.\n\n"
        "  --action=close --confirm-close\n"
        "      Cierra la posición al precio actual (vía YahooProvider) -\n"
        "      requiere --confirm-close explícito: cerrar una posición\n"
        "      real es una decisión financiera, no algo que este script\n"
        "      decida solo.\n"
    )


def _accion_migrate(position_id: int) -> int:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT symbol, asset_class FROM portfolio WHERE id = ?", (position_id,)
        ).fetchone()
        if fila is None:
            print(f"No existe la posición id={position_id}.")
            return 1

        symbol, asset_class_actual = fila
        if asset_class_actual == "crypto":
            print(
                f"Posición {position_id} ({symbol}) ya está unificada "
                f"(asset_class='crypto'). No se necesita ningún cambio."
            )
            return 0

        normalized_symbol = normalizar_symbol(symbol, "crypto")
        conn.execute(
            "UPDATE portfolio SET asset_class = 'crypto', normalized_symbol = ? WHERE id = ?",
            (normalized_symbol, position_id),
        )
        conn.commit()
        print(
            f"Posición {position_id} ({symbol}) migrada: asset_class='crypto', "
            f"normalized_symbol='{normalized_symbol}'. Sigue OPEN."
        )
        return 0
    finally:
        conn.close()


def _accion_close(position_id: int) -> int:
    stock = YahooProvider().get_stock(STALE_BTC_SYMBOL)
    resultado = portfolio_service.sell_position(position_id, stock.price)

    if resultado is None:
        print(f"No se pudo cerrar la posición {position_id} (no existe o ya está cerrada).")
        return 1

    print(
        f"Posición {position_id} cerrada a ${stock.price:,.2f} - "
        f"P&L: ${resultado['pnl']:,.2f} ({resultado['profit_pct']:.2f}%)."
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Resuelve la posición BTC-USD estancada (el operador decide)."
    )
    parser.add_argument("--action", choices=["migrate", "close"], default=None)
    parser.add_argument("--confirm-close", action="store_true")
    parser.add_argument(
        "--position-id",
        type=int,
        default=STALE_BTC_POSITION_ID,
        help="Solo para pruebas - en producción siempre es la posición real (id=2).",
    )
    args = parser.parse_args(argv)

    if args.action is None:
        _imprimir_opciones()
        return 2

    if args.action == "migrate":
        return _accion_migrate(args.position_id)

    # args.action == "close" (única opción restante dado choices=[...])
    if not args.confirm_close:
        print(
            "--action=close requiere también --confirm-close: cerrar una "
            "posición real es una decisión financiera, no algo que este "
            "script haga sin confirmación explícita. No se tocó la base de datos."
        )
        return 2

    return _accion_close(args.position_id)


if __name__ == "__main__":
    sys.exit(main())
