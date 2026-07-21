from portfolio import (
    get_open_positions,
    add_position,
    sell_position
)

from signal_manager import (
    mark_as_executed
)


def portfolio_command():

    positions = get_open_positions()

    message = "\n===== PORTAFOLIO =====\n\n"

    if not positions:

        return (
            message +
            "No existen posiciones abiertas."
        )

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

        invested = (
            quantity *
            buy_price
        )

        total += invested

        message += (

            f"ID: {position_id}\n"
            f"Activo: {symbol}\n"
            f"Cantidad: {quantity}\n"
            f"Compra: {buy_price}\n"
            f"Objetivo: {target_price}\n"
            f"Stop: {stop_loss}\n"
            f"Invertido: ${invested:,.2f}\n"
            f"{'-'*40}\n"

        )

    message += (
        f"\nTOTAL: "
        f"${total:,.2f}"
    )

    return message


def buy_command(

    signal_id,
    symbol,
    quantity,
    buy_price,
    target_price,
    stop_loss

):

    add_position(

        symbol,
        int(quantity),
        float(buy_price),
        float(target_price),
        float(stop_loss)

    )

    mark_as_executed(
        int(signal_id)
    )

    return (

        "POSICIÓN AGREGADA\n\n"

        f"Signal ID: {signal_id}\n"
        f"Activo: {symbol}\n"
        f"Cantidad: {quantity}\n"
        f"Compra: {buy_price}\n"
        f"Objetivo: {target_price}\n"
        f"Stop: {stop_loss}"

    )


def sell_command(

    position_id,
    sell_price

):

    sell_position(

        int(position_id),
        float(sell_price)

    )

    return (

        "POSICIÓN CERRADA\n\n"
        f"ID: {position_id}\n"
        f"Precio Venta: {sell_price}"

    )


if __name__ == "__main__":

    print(
        portfolio_command()
    )