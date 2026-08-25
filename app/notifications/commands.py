"""
Comandos de Telegram unificados (Épica 7): reemplaza telegram_commands.py
(acciones + portfolio legacy) y crypto_telegram_commands.py (cripto),
que hasta ahora usaban dos estilos de manejo de comandos distintos y
dos representaciones de portfolio separadas - la causa raíz de la
posición BTC-USD huérfana que encontró la auditoría.

portfolio_command/comprar_command/sell_command/vender_command/
mantener_command se reescriben contra app.services.portfolio_service
(Épica 4) en vez de portfolio.py - portfolio_service es la ÚNICA
superficie de escritura de portfolio que este módulo usa.
analisis_command se porta sin cambios (nunca toca el portfolio).
cripto_command se mueve tal cual desde crypto_telegram_commands.py
(persistir=False, de solo lectura, sin cambios).

Alcance ampliado respecto a la primera versión de esta tarea: el
blueprint original solo nombraba portfolio_command/comprar_command/
vender_command/mantener_command/cripto_command, lo que habría hecho
imposible cumplir el criterio de "cero imports de telegram_commands"
de E7-T2 sin dejar de soportar /sell y /analisis - comandos reales del
bot actual. Confirmado con el operador: se portan también
sell_command y analisis_command.

telegram_commands.py y crypto_telegram_commands.py NO se eliminan
acá - quedan sin registrar, como peso muerto hasta que la Épica 8 los
borre tras el período de observación.
"""

from app.ai.ollama_analyzer import AnalisisNoDisponible, analizar_activo
from app.core.settings import Settings
from app.database import obtener_senal
from app.notifications.crypto_telegram_commands import cripto_command
from app.services import portfolio_service
from signal_manager import mark_as_executed

STOP_INICIAL_PCT = 0.01  # -1% desde la entrada
OBJETIVO_INICIAL_PCT = 0.03  # +3% desde la entrada


def _asset_class_de(symbol: str) -> str:
    return "crypto" if symbol in Settings.ACTIVOS_CRIPTO else "stock"


def portfolio_command():
    positions = portfolio_service.get_open_positions()

    message = "\n===== PORTAFOLIO =====\n\n"

    if not positions:
        return message + "No existen posiciones abiertas."

    total = 0
    for p in positions:
        invested = p["quantity"] * p["buy_price"]
        total += invested

        message += (
            f"ID: {p['id']}\n"
            f"Activo: {p['symbol']} ({p['asset_class']})\n"
            f"Cantidad: {p['quantity']}\n"
            f"Compra: {p['buy_price']}\n"
            f"Objetivo: {p['target_price']}\n"
            f"Stop: {p['stop_loss']}\n"
            f"Invertido: ${invested:,.2f}\n"
            f"{'-' * 40}\n"
        )

    message += f"\nTOTAL: ${total:,.2f}"
    return message


def comprar_command(signal_id, quantity):
    """Compra una posición a partir de una señal (antes /buy).

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
    asset_class = _asset_class_de(symbol)

    position_id = portfolio_service.add_position(
        symbol,
        quantity,
        buy_price,
        asset_class,
        target_price=target_price,
        stop_loss=stop_loss,
    )

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


def sell_command(position_id, sell_price):
    """Cierra una posición manualmente, en cualquier momento (sin
    registrar una decisión de stop-loss)."""
    portfolio_service.sell_position(int(position_id), float(sell_price))

    return (
        "POSICIÓN CERRADA\n\n"
        f"ID: {position_id}\n"
        f"Precio Venta: {sell_price}"
    )


def vender_command(position_id, sell_price):
    """Cierra la posición en respuesta a una alerta de stop loss, y registra la decisión."""
    position_id = int(position_id)
    sell_price = float(sell_price)

    portfolio_service.sell_position(position_id, sell_price)
    portfolio_service.registrar_decision(position_id, "VENDER", sell_price)

    return (
        "POSICIÓN CERRADA (por stop loss)\n\n"
        f"ID: {position_id}\n"
        f"Precio Venta: {sell_price}"
    )


def mantener_command(position_id):
    """Registra que decidiste mantener la posición pese al stop loss."""
    position_id = int(position_id)

    portfolio_service.registrar_decision(position_id, "MANTENER", None)

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


COMMANDS = {
    "portfolio": portfolio_command,
    "comprar": comprar_command,
    "sell": sell_command,
    "vender": vender_command,
    "mantener": mantener_command,
    "analisis": analisis_command,
    "cripto": cripto_command,
}
