"""
Envío de mensajes por Telegram, centralizado.

Antes existían 3 copias distintas de esta misma lógica (scoring.py,
portfolio_alerts.py, y una versión con HTML sin usar). Este módulo es
ahora la única fuente de verdad; todo lo demás lo importa desde aquí.
"""

import os

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def enviar_mensaje_telegram(mensaje):
    """Envía un mensaje de texto plano al chat configurado.

    Devuelve el código de estado HTTP si se envió, o None si falló
    (nunca lanza una excepción hacia quien la llama).
    """

    try:
        respuesta = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": mensaje},
            timeout=10,
        )
        return respuesta.status_code

    except Exception:
        logger.exception("Error enviando mensaje de Telegram")
        return None