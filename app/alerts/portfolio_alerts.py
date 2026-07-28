"""
Alertas de portafolio y trailing stop (stop loss dinámico).

Cada ciclo, para cada posición abierta:
  1. Revisa si el precio alcanzó el objetivo -> si sí, ese nivel se convierte
     en el nuevo stop loss y el objetivo sube otro 3% (trailing stop).
  2. Revisa si el precio cayó al stop loss vigente -> si sí, envía una alerta
     con opciones (/vender, /mantener) y espera tu decisión. No vende sola.
  3. Envía un aviso de cuánto ha crecido/caído la posición desde la compra.

Las alertas de una posición se detienen automáticamente cuando se cierra
(get_open_positions() solo devuelve posiciones con status='OPEN').
"""

import yfinance as yf
from loguru import logger

from portfolio import get_open_positions, actualizar_trailing_stop, marcar_alerta_stop
from app.services.telegram_service import enviar_mensaje_telegram

TRAILING_STEP_PCT = 0.03  # 3%


def _revisar_trailing_stop(position_id, symbol, precio_actual, stop_loss, target_price):
    """Si el precio alcanzó el objetivo, sube el stop y el objetivo (trailing).

    Devuelve (stop_loss, target_price) actualizados para seguir usando en
    el resto del ciclo.
    """

    while target_price is not None and precio_actual >= target_price:
        nuevo_stop = target_price
        nuevo_target = target_price * (1 + TRAILING_STEP_PCT)

        actualizar_trailing_stop(position_id, nuevo_stop, nuevo_target)

        codigo = enviar_mensaje_telegram(
            f"""
📈 ROBOTINAIA - TRAILING STOP

Activo         : {symbol}
Precio Actual  : ${precio_actual:,.2f}
Nuevo Stop     : ${nuevo_stop:,.2f}
Nuevo Objetivo : ${nuevo_target:,.2f}

La posición sigue abierta, dejando correr la ganancia.
"""
        )
        logger.info(f"{symbol}: trailing stop subido -> TELEGRAM ({codigo})")

        stop_loss, target_price = nuevo_stop, nuevo_target

    return stop_loss, target_price


def _revisar_stop_loss(position_id, symbol, precio_actual, stop_loss, alerta_stop_enviada):
    """Si el precio tocó el stop, alerta con opciones (una sola vez por cruce)."""

    if stop_loss is None:
        return

    if precio_actual <= stop_loss:
        if alerta_stop_enviada:
            return  # ya se avisó de este cruce, se espera tu decisión

        codigo = enviar_mensaje_telegram(
            f"""
🚨 ROBOTINAIA - STOP LOSS ALCANZADO

Activo         : {symbol}
Precio Actual  : ${precio_actual:,.2f}
Stop Loss      : ${stop_loss:,.2f}

Elige una opción:
/vender {position_id} {precio_actual:.2f}   -> cerrar la posición ahora
/mantener {position_id}   -> ignorar por ahora, seguir con el mismo stop
"""
        )
        logger.info(f"{symbol}: alerta de stop loss -> TELEGRAM ({codigo})")
        marcar_alerta_stop(position_id, True)

    else:
        if alerta_stop_enviada:
            # El precio se recuperó por encima del stop: se rearma la alerta
            # para que un futuro cruce vuelva a notificar.
            marcar_alerta_stop(position_id, False)


def _enviar_aviso_crecimiento(symbol, buy_price, precio_actual):
    crecimiento_pct = ((precio_actual - buy_price) / buy_price) * 100
    emoji = "🟢" if crecimiento_pct >= 0 else "🔴"

    codigo = enviar_mensaje_telegram(
        f"""
{emoji} ROBOTINAIA - ESTADO DE POSICIÓN

Activo         : {symbol}
Compra         : ${buy_price:,.2f}
Precio Actual  : ${precio_actual:,.2f}
Variación      : {crecimiento_pct:+.2f}%
"""
    )
    logger.info(f"{symbol}: aviso de crecimiento ({crecimiento_pct:+.2f}%) -> TELEGRAM ({codigo})")


def revisar_alertas_portafolio():
    """Revisa todas las posiciones abiertas: trailing stop, stop loss y crecimiento."""

    posiciones = get_open_positions()

    logger.info(f"Revisando alertas de portafolio: {len(posiciones)} posición(es) abierta(s)")

    for (
        position_id,
        symbol,
        quantity,
        buy_price,
        buy_date,
        target_price,
        stop_loss,
        alerta_stop_enviada,
    ) in posiciones:
        try:
            data = yf.Ticker(symbol).history(period="1d", interval="5m")

            if data.empty:
                logger.warning(f"{symbol}: sin datos para revisar alertas de portafolio")
                continue

            precio_actual = float(data.iloc[-1]["Close"])

            logger.info(
                f"{symbol}: precio actual={precio_actual:.2f} | "
                f"objetivo={target_price} | stop={stop_loss}"
            )

            stop_loss, target_price = _revisar_trailing_stop(
                position_id, symbol, precio_actual, stop_loss, target_price
            )

            _revisar_stop_loss(position_id, symbol, precio_actual, stop_loss, alerta_stop_enviada)

            _enviar_aviso_crecimiento(symbol, buy_price, precio_actual)

        except Exception:
            logger.exception(f"Error revisando alertas de portafolio para {symbol}")