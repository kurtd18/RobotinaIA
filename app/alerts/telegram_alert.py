from telegram import Bot
from datetime import datetime
import asyncio
import os


class TelegramAlert:

    def __init__(self):

        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    async def send_message(self, message: str):

        try:

            bot = Bot(token=self.token)

            await bot.send_message(
                chat_id=self.chat_id,
                text=message
            )

            print("✅ Alerta enviada correctamente.")

        except Exception as error:

            print(f"❌ Error enviando alerta: {error}")

    async def send_portfolio_alert(
        self,
        symbol,
        current_price,
        percentage,
        recommendation
    ):

        message = f"""
🚨 ROBOTINAIA ALERT

Activo         : {symbol}
Precio Actual  : ${current_price:,.2f}
Variación      : {percentage:.2f}%
Recomendación  : {recommendation}

Fecha:
{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""

        await self.send_message(message)


async def main():

    alert = TelegramAlert()

    await alert.send_portfolio_alert(
        symbol="MINEROS",
        current_price=15680,
        percentage=1.55,
        recommendation="MANTENER"
    )


if __name__ == "__main__":
    asyncio.run(main())