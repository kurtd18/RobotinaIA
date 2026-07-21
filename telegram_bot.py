import os

from dotenv import load_dotenv

from telegram import Update

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

from telegram_commands import (
    portfolio_command,
    buy_command,
    sell_command
)

load_dotenv()

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        """
RobotinaIA V7

Comandos:

/help
/ping
/portfolio
/buy
/sell
"""
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        """
COMANDOS DISPONIBLES

/ping

/portfolio

/buy SIGNAL_ID ACTIVO CANTIDAD PRECIO OBJETIVO STOP

Ejemplo:

/buy 15 MINEROS.CL 73 15440 16500 14800

/sell ID PRECIO

Ejemplo:

/sell 1 16120
"""
    )


async def ping(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "RobotinaIA ONLINE"
    )


async def portfolio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mensaje = portfolio_command()

    await update.message.reply_text(
        mensaje
    )


async def buy(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        args = context.args

        if len(args) != 6:

            await update.message.reply_text(
                "Uso:\n"
                "/buy SIGNAL_ID ACTIVO "
                "CANTIDAD PRECIO "
                "OBJETIVO STOP"
            )

            return

        mensaje = buy_command(

            args[0],
            args[1],
            args[2],
            args[3],
            args[4],
            args[5]

        )

        await update.message.reply_text(
            mensaje
        )

    except Exception as e:

        await update.message.reply_text(
            f"ERROR: {e}"
        )


async def sell(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        args = context.args

        if len(args) != 2:

            await update.message.reply_text(
                "Uso:\n"
                "/sell ID PRECIO"
            )

            return

        mensaje = sell_command(
            args[0],
            args[1]
        )

        await update.message.reply_text(
            mensaje
        )

    except Exception as e:

        await update.message.reply_text(
            f"ERROR: {e}"
        )


def main():

    print(
        "Iniciando Telegram Bot..."
    )

    app = (

        ApplicationBuilder()
        .token(TOKEN)
        .build()

    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "ping",
            ping
        )
    )

    app.add_handler(
        CommandHandler(
            "portfolio",
            portfolio
        )
    )

    app.add_handler(
        CommandHandler(
            "buy",
            buy
        )
    )

    app.add_handler(
        CommandHandler(
            "sell",
            sell
        )
    )

    print(
        "RobotinaIA escuchando..."
    )

    app.run_polling()


if __name__ == "__main__":

    main()