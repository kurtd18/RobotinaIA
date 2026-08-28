from portfolio import get_open_positions


def portfolio_command():

    positions = get_open_positions()

    message = "\n===== PORTAFOLIO =====\n\n"

    if not positions:
        return message + "No existen posiciones abiertas."

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

        message += (
            f"ID: {position_id}\n"
            f"Activo: {symbol}\n"
            f"Cantidad: {quantity}\n"
            f"Compra: {buy_price}\n"
            f"Invertido: ${invested:,.2f}\n"
            f"Objetivo: {target_price}\n"
            f"Stop: {stop_loss}\n"
            f"{'-'*30}\n"
        )

    message += f"\nTOTAL: ${total:,.2f}"

    return message


if __name__ == "__main__":

    print(
        portfolio_command()
    )   