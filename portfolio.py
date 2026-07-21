import sqlite3
from datetime import datetime

DB_NAME = "robotinaia.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def add_position(
    symbol,
    quantity,
    buy_price,
    target_price=None,
    stop_loss=None
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO portfolio (
            symbol,
            quantity,
            buy_price,
            buy_date,
            target_price,
            stop_loss,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol.upper(),
            quantity,
            buy_price,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            target_price,
            stop_loss,
            "OPEN"
        )
    )

    conn.commit()
    conn.close()

    print(f"Posición agregada: {symbol}")


def get_open_positions():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            symbol,
            quantity,
            buy_price,
            buy_date,
            target_price,
            stop_loss
        FROM portfolio
        WHERE status = 'OPEN'
        ORDER BY id
        """
    )

    rows = cursor.fetchall()

    conn.close()

    return rows


def sell_position(position_id, sell_price):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT quantity, buy_price
        FROM portfolio
        WHERE id = ?
        """,
        (position_id,)
    )

    result = cursor.fetchone()

    if not result:
        print("Posición no encontrada.")
        conn.close()
        return

    quantity, buy_price = result

    profit = (sell_price - buy_price) * quantity
    profit_pct = ((sell_price - buy_price) / buy_price) * 100

    cursor.execute(
        """
        UPDATE portfolio
        SET
            status='CLOSED',
            sell_price=?,
            sell_date=?
        WHERE id=?
        """,
        (
            sell_price,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            position_id
        )
    )

    conn.commit()
    conn.close()

    print("\n===== POSICIÓN CERRADA =====")
    print(f"Ganancia: ${profit:,.2f}")
    print(f"Rentabilidad: {profit_pct:.2f}%")


def show_portfolio():

    positions = get_open_positions()

    print("\n===== ROBOTINAIA PORTAFOLIO =====\n")

    if not positions:
        print("No existen posiciones abiertas.")
        return

    total = 0

    for position in positions:

        (
            position_id,
            symbol,
            quantity,
            buy_price,
            buy_date,
            target_price,
            stop_loss
        ) = position

        invested = quantity * buy_price
        total += invested

        print(f"ID: {position_id}")
        print(f"Activo: {symbol}")
        print(f"Cantidad: {quantity}")
        print(f"Precio Compra: {buy_price}")
        print(f"Fecha Compra: {buy_date}")
        print(f"Objetivo: {target_price}")
        print(f"Stop Loss: {stop_loss}")
        print(f"Invertido: ${invested:,.2f}")
        print("-" * 40)

    print(f"\nTOTAL INVERTIDO: ${total:,.2f}")


if __name__ == "__main__":

    # DESCOMENTAR SOLO PARA PRUEBAS
    #
    # add_position(
    #     "MINEROS.CL",
    #     73,
    #     15440,
    #     16500,
    #     14800
    # )

    show_portfolio()

    # DESCOMENTAR SOLO PARA PRUEBAS
    #
    # sell_position(
    #     1,
    #     16120
    # )