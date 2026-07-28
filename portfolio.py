"""
Gestión del portafolio: alta de posiciones, consulta, cierre (venta),
y soporte para el trailing stop (stop loss dinámico).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.database.connection import get_connection

TZ_BOGOTA = ZoneInfo("America/Bogota")


def _now_str():
    return datetime.now(TZ_BOGOTA).strftime("%Y-%m-%d %H:%M:%S%z")


def add_position(symbol, quantity, buy_price, target_price=None, stop_loss=None):
    if quantity <= 0 or buy_price <= 0:
        logger.warning(f"{symbol}: cantidad y precio de compra deben ser mayores a 0")
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO portfolio (
            symbol, quantity, buy_price, buy_date,
            target_price, stop_loss, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (symbol.upper(), quantity, buy_price, _now_str(), target_price, stop_loss, "OPEN"),
    )

    position_id = cursor.lastrowid

    conn.commit()
    conn.close()
    logger.info(f"Posición agregada: {symbol} (ID {position_id})")

    return position_id


def get_open_positions():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, symbol, quantity, buy_price, buy_date, target_price,
               stop_loss, alerta_stop_enviada
        FROM portfolio WHERE status = 'OPEN' ORDER BY id
        """
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


def sell_position(position_id, sell_price):
    if sell_price <= 0:
        logger.warning("El precio de venta debe ser mayor a 0.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT quantity, buy_price FROM portfolio WHERE id = ? AND status = 'OPEN'",
        (position_id,),
    )
    result = cursor.fetchone()

    if not result:
        logger.warning(f"Posición {position_id} no encontrada o ya está cerrada.")
        conn.close()
        return

    quantity, buy_price = result
    profit = (sell_price - buy_price) * quantity
    profit_pct = ((sell_price - buy_price) / buy_price) * 100

    cursor.execute(
        "UPDATE portfolio SET status='CLOSED', sell_price=?, sell_date=? WHERE id=?",
        (sell_price, _now_str(), position_id),
    )

    conn.commit()
    conn.close()
    logger.info(f"Posición {position_id} cerrada | Ganancia: ${profit:,.2f} | Rentabilidad: {profit_pct:.2f}%")


def actualizar_trailing_stop(position_id, nuevo_stop, nuevo_target):
    """Actualiza el stop loss y objetivo de una posición (stop loss dinámico)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE portfolio SET stop_loss=?, target_price=? WHERE id=?",
        (nuevo_stop, nuevo_target, position_id),
    )

    conn.commit()
    conn.close()

    logger.info(f"Posición {position_id}: trailing stop actualizado -> stop={nuevo_stop:.2f} objetivo={nuevo_target:.2f}")


def marcar_alerta_stop(position_id, enviada: bool):
    """Marca si ya se envió la alerta de 'toca el stop' para esta posición,
    para no repetirla cada ciclo mientras se espera tu decisión."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE portfolio SET alerta_stop_enviada=? WHERE id=?",
        (1 if enviada else 0, position_id),
    )

    conn.commit()
    conn.close()


def registrar_decision(position_id, decision, precio):
    """Guarda la decisión que tomaste (MANTENER/VENDER) cuando se tocó el stop."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO portfolio_decisions (position_id, decision, precio, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (position_id, decision, precio, _now_str()),
    )

    conn.commit()
    conn.close()

    logger.info(f"Posición {position_id}: decisión registrada -> {decision}")


def show_portfolio():
    positions = get_open_positions()

    if not positions:
        logger.info("No existen posiciones abiertas.")
        return

    total = 0
    for position_id, symbol, quantity, buy_price, buy_date, target_price, stop_loss, _ in positions:
        invested = quantity * buy_price
        total += invested
        logger.info(
            f"ID: {position_id} | {symbol} | Cant: {quantity} | Compra: {buy_price} "
            f"({buy_date}) | Objetivo: {target_price} | Stop: {stop_loss} | Invertido: ${invested:,.2f}"
        )

    logger.info(f"TOTAL INVERTIDO: ${total:,.2f}")


if __name__ == "__main__":
    show_portfolio()