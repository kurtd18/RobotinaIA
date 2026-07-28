from portfolio import (
    get_open_positions,
    add_position,
    sell_position,
    registrar_decision,
)

from signal_manager import (
    mark_as_executed
)

from app.ai.ollama_analyzer import analizar_activo, AnalisisNoDisponible
from app.core.settings import Settings
from app.database import obtener_senal

STOP_INICIAL_PCT = 0.01     # -1% desde la entrada
OBJETIVO_INICIAL_PCT = 0.03  # +3% desde la entrada


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
            stop_loss,
            _alerta_stop_enviada,
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


def buy_command(signal_id, quantity):
    """Compra una posición a partir de una señal.

    El precio de entrada se toma de la señal, y el stop loss (-1%) y el
    objetivo (+3%) se calculan automáticamente a partir de ese precio.
    """

    signal_id = int(signal_id)
    quantity = int(quantity)

    senal = obtener_senal(signal_id)

    if senal is None:
        return f"No se encontró la señal con ID {signal_id}."

    symbol, buy_price = senal

    stop_loss = buy_price * (1 - STOP_INICIAL_PCT)
    target_price = buy_price * (1 + OBJETIVO_INICIAL_PCT)

    position_id = add_position(symbol, quantity, buy_price, target_price, stop_loss)

    mark_as_executed(signal_id)

    return (

        "POSICIÓN AGREGADA\n\n"

        f"Position ID: {position_id}\n"
        f"Signal ID: {signal_id}\n"
        f"Activo: {symbol}\n"
        f"Cantidad: {quantity}\n"
        f"Compra: {buy_price:.2f}\n"
        f"Objetivo: {target_price:.2f}\n"
        f"Stop: {stop_loss:.2f}"

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


def vender_command(position_id, sell_price):
    """Cierra la posición en respuesta a una alerta de stop loss, y registra la decisión."""

    position_id = int(position_id)
    sell_price = float(sell_price)

    sell_position(position_id, sell_price)
    registrar_decision(position_id, "VENDER", sell_price)

    return (
        "POSICIÓN CERRADA (por stop loss)\n\n"
        f"ID: {position_id}\n"
        f"Precio Venta: {sell_price}"
    )


def mantener_command(position_id):
    """Registra que decidiste mantener la posición pese al stop loss."""

    position_id = int(position_id)

    registrar_decision(position_id, "MANTENER", None)

    return (
        f"Posición {position_id}: decisión registrada -> MANTENER.\n"
        "Se sigue vigilando con el mismo stop loss."
    )


def analisis_command(symbol):

    symbol = symbol.upper()

    if symbol not in Settings.todos_los_activos():
        return (
            f"'{symbol}' no está en la lista de activos monitoreados.\n\n"
            f"Activos disponibles: {', '.join(Settings.todos_los_activos())}"
        )

    try:
        return analizar_activo(symbol)
    except AnalisisNoDisponible as e:
        return f"No se pudo generar el análisis de {symbol}: {e}"


if __name__ == "__main__":

    print(
        portfolio_command()
    )