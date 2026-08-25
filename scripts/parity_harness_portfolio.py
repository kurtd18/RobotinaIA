"""
Compara, para cada posición CLOSED, el P&L "viejo" (fórmula inline:
(sell_price - buy_price) * quantity, la que portfolio.py siempre usó)
contra el que produce el camino nuevo (FeeConfig.apply(...), el mismo
que usa internamente app/services/portfolio_service.py.sell_position) -
deben coincidir exactamente mientras STOCK_FEE_CONFIG/CRYPTO_FEE_CONFIG
sigan sin configurar (fee_pct=0), que es el estado actual.

Si algún día se configuran comisiones reales, este harness dejaría de
pasar para las posiciones cerradas DESPUÉS de ese cambio - eso es
correcto, no un bug: el P&L legítimamente cambia cuando las comisiones
son reales, y este harness solo garantiza paridad mientras no lo son.

Uso:
    python scripts/parity_harness_portfolio.py
    # exit 0 -> 0 discrepancias
    # exit 1 -> imprime cada fila con discrepancia (id, viejo, nuevo)
"""

import sys
from pathlib import Path

# Al correr "python scripts/parity_harness_portfolio.py", Python agrega
# el directorio del script a sys.path, no la raíz del repo - mismo fix
# que los scripts de migrations/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.connection import get_connection
from app.services.fee_config import CRYPTO_FEE_CONFIG, STOCK_FEE_CONFIG

_FEE_CONFIGS = {"stock": STOCK_FEE_CONFIG, "crypto": CRYPTO_FEE_CONFIG}


def calcular_pnl_viejo(sell_price: float, buy_price: float, quantity: float) -> float:
    """La fórmula inline que portfolio.py.sell_position siempre usó."""
    return (sell_price - buy_price) * quantity


def calcular_pnl_nuevo(
    sell_price: float, buy_price: float, quantity: float, asset_class: str
) -> float:
    """El mismo camino que portfolio_service.sell_position usa
    internamente: P&L bruto + FeeConfig.apply(...) de su asset_class."""
    gross_pnl = calcular_pnl_viejo(sell_price, buy_price, quantity)
    fee_config = _FEE_CONFIGS[asset_class]
    net_pnl, _configured = fee_config.apply(gross_pnl, quantity, sell_price)
    return net_pnl


def main() -> int:
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT id, buy_price, sell_price, quantity, asset_class "
            "FROM portfolio WHERE status = 'CLOSED'"
        ).fetchall()
    finally:
        conn.close()

    discrepancias = []
    for position_id, buy_price, sell_price, quantity, asset_class in filas:
        pnl_viejo = calcular_pnl_viejo(sell_price, buy_price, quantity)
        pnl_nuevo = calcular_pnl_nuevo(sell_price, buy_price, quantity, asset_class)

        if pnl_viejo != pnl_nuevo:
            discrepancias.append((position_id, pnl_viejo, pnl_nuevo))

    print(f"Posiciones CLOSED revisadas: {len(filas)}")
    print(f"Discrepancias encontradas: {len(discrepancias)}")

    if discrepancias:
        for position_id, pnl_viejo, pnl_nuevo in discrepancias:
            print(f"  id={position_id}: viejo={pnl_viejo!r} nuevo={pnl_nuevo!r}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
