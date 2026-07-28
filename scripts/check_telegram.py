"""
Chequeo manual de conectividad con Telegram: envía un mensaje de prueba.

Uso: python scripts/check_telegram.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_service import enviar_mensaje_telegram


def check_telegram():
    codigo = enviar_mensaje_telegram("¡Hola! RobotinaIA está funcionando correctamente.")

    if codigo == 200:
        print(f"OK: mensaje enviado correctamente (status {codigo})")
    else:
        print(f"ERROR: no se pudo enviar el mensaje (status {codigo})")


if __name__ == "__main__":
    check_telegram()