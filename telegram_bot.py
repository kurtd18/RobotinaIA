import os

from dotenv import load_dotenv
from loguru import logger

from telegram import Update

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

from app.notifications.commands import (
    portfolio_command,
    comprar_command,
    sell_command,
    vender_command,
    mantener_command,
    analisis_command,
    cripto_command,
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
RobotinaIA V7

Comandos:

/help
/ping
/portfolio
/comprar
/sell
/vender
/mantener
/analisis
/cripto
"""
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
COMANDOS DISPONIBLES

/ping

/portfolio

/comprar SIGNAL_ID CANTIDAD

Compra a partir de una señal. El precio de entrada, el stop (-1%) y el
objetivo (+3%) se calculan automáticamente.

Ejemplo:

/comprar 15 73

/sell ID PRECIO

Cierra una posición manualmente en cualquier momento.

Ejemplo:

/sell 1 16120

/vender ID PRECIO

Cierra una posición en respuesta a una alerta de stop loss.

Ejemplo:

/vender 2 64500

/mantener ID

Mantiene la posición abierta pese a la alerta de stop loss.

Ejemplo:

/mantener 2

/analisis ACTIVO

Ejemplo:

/analisis MINEROS.CL

/cripto

Análisis en vivo de BTC/USDT y ETH/USDT (RobotinaIA Crypto). Consulta
de solo lectura - no abre posiciones de paper trading, eso solo lo
hace la corrida programada.
"""
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("RobotinaIA ONLINE")


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = portfolio_command()
    await update.message.reply_text(mensaje)


async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Uso:\n/comprar SIGNAL_ID CANTIDAD")
        return

    try:
        mensaje = comprar_command(args[0], args[1])
        await update.message.reply_text(mensaje)

    except ValueError:
        await update.message.reply_text("SIGNAL_ID y CANTIDAD deben ser valores numéricos.")

    except Exception:
        logger.exception("Error procesando /comprar")
        await update.message.reply_text(
            "Ocurrió un error procesando la compra. Intenta de nuevo más tarde."
        )


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Uso:\n/sell ID PRECIO")
        return

    try:
        mensaje = sell_command(args[0], args[1])
        await update.message.reply_text(mensaje)

    except ValueError:
        await update.message.reply_text("ID y PRECIO deben ser valores numéricos.")

    except Exception:
        logger.exception("Error procesando /sell")
        await update.message.reply_text(
            "Ocurrió un error procesando la venta. Intenta de nuevo más tarde."
        )


async def vender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Uso:\n/vender ID PRECIO")
        return

    try:
        mensaje = vender_command(args[0], args[1])
        await update.message.reply_text(mensaje)

    except ValueError:
        await update.message.reply_text("ID y PRECIO deben ser valores numéricos.")

    except Exception:
        logger.exception("Error procesando /vender")
        await update.message.reply_text(
            "Ocurrió un error procesando la venta. Intenta de nuevo más tarde."
        )


async def mantener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) != 1:
        await update.message.reply_text("Uso:\n/mantener ID")
        return

    try:
        mensaje = mantener_command(args[0])
        await update.message.reply_text(mensaje)

    except ValueError:
        await update.message.reply_text("ID debe ser un valor numérico.")

    except Exception:
        logger.exception("Error procesando /mantener")
        await update.message.reply_text(
            "Ocurrió un error registrando la decisión. Intenta de nuevo más tarde."
        )


async def analisis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) != 1:
        await update.message.reply_text("Uso:\n/analisis ACTIVO\n\nEjemplo:\n/analisis MINEROS.CL")
        return

    await update.message.reply_text(f"Generando análisis de {args[0].upper()}, un momento...")

    try:
        mensaje = analisis_command(args[0])
        await update.message.reply_text(mensaje)

    except Exception:
        logger.exception(f"Error procesando /analisis para {args[0]}")
        await update.message.reply_text(
            "Ocurrió un error generando el análisis. Intenta de nuevo más tarde."
        )


async def cripto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Generando análisis cripto (BTC/USDT, ETH/USDT), un momento...")

    try:
        mensaje = cripto_command()
        await update.message.reply_text(mensaje)

    except Exception:
        logger.exception("Error procesando /cripto")
        await update.message.reply_text(
            "Ocurrió un error generando el análisis cripto. Intenta de nuevo más tarde."
        )


def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN no está configurado en el .env")
        return

    logger.info("Iniciando Telegram Bot...")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("comprar", comprar))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("vender", vender))
    app.add_handler(CommandHandler("mantener", mantener))
    app.add_handler(CommandHandler("analisis", analisis))
    app.add_handler(CommandHandler("cripto", cripto))

    logger.info("RobotinaIA escuchando...")

    app.run_polling()


if __name__ == "__main__":
    main()