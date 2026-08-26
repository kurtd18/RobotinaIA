"""Test del wrapper async de /portfolio en telegram_bot.py.

Encontrado durante la observación en producción de E8-T2: a diferencia
de los otros 6 comandos, /portfolio no tenía try/except - si
portfolio_command() fallaba, el usuario no recibía ningún mensaje
(silencio total) en vez de un error legible."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import telegram_bot


def _fake_update():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def test_portfolio_wrapper_replies_with_error_message_on_exception():
    update = _fake_update()

    with patch(
        "telegram_bot.portfolio_command", side_effect=RuntimeError("fallo simulado")
    ):
        asyncio.run(telegram_bot.portfolio(update, MagicMock()))

    update.message.reply_text.assert_called_once()
    mensaje_enviado = update.message.reply_text.call_args.args[0]
    assert "error" in mensaje_enviado.lower()


def test_portfolio_wrapper_replies_with_the_real_message_on_success():
    update = _fake_update()

    with patch("telegram_bot.portfolio_command", return_value="PORTAFOLIO OK"):
        asyncio.run(telegram_bot.portfolio(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("PORTAFOLIO OK")
