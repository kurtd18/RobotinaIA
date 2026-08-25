"""Tests de telegram_bot.py: cutover a app.notifications.commands (E7-T2)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import telegram_bot
from app.notifications import commands as commands_module

_COMANDOS_UNIFICADOS_ESPERADOS = {
    "portfolio", "comprar", "sell", "vender", "mantener", "analisis", "cripto",
}


def test_source_has_zero_legacy_command_module_references():
    source = Path(telegram_bot.__file__).read_text(encoding="utf-8")
    assert "telegram_commands" not in source
    assert "crypto_telegram_commands" not in source


def test_wrapper_functions_reference_the_unified_commands_module():
    # Cada función importada en telegram_bot.py debe ser exactamente la
    # misma que expone app.notifications.commands - no una copia local
    # ni algo todavía apuntando a telegram_commands.
    assert telegram_bot.portfolio_command is commands_module.portfolio_command
    assert telegram_bot.comprar_command is commands_module.comprar_command
    assert telegram_bot.sell_command is commands_module.sell_command
    assert telegram_bot.vender_command is commands_module.vender_command
    assert telegram_bot.mantener_command is commands_module.mantener_command
    assert telegram_bot.analisis_command is commands_module.analisis_command
    assert telegram_bot.cripto_command is commands_module.cripto_command


def test_registered_handlers_cover_all_seven_unified_commands():
    handlers_registrados = []

    class FakeTelegramApp:
        def add_handler(self, handler):
            handlers_registrados.append(handler)

        def run_polling(self):
            pass

    fake_app = FakeTelegramApp()
    fake_builder = MagicMock()
    fake_builder.token.return_value.build.return_value = fake_app

    with patch("telegram_bot.ApplicationBuilder", return_value=fake_builder), \
         patch("telegram_bot.TOKEN", "fake-token-for-test"):
        telegram_bot.main()

    comandos_registrados = set()
    for handler in handlers_registrados:
        comandos_registrados.update(handler.commands)

    assert _COMANDOS_UNIFICADOS_ESPERADOS <= comandos_registrados
    assert "buy" not in comandos_registrados  # renombrado a /comprar, no coexiste
