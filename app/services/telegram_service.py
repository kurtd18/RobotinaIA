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


def enviar_mensaje_telegram(mensaje, parse_mode=None):
    """Envía un mensaje al chat configurado.

    parse_mode: None (texto plano, comportamiento original) o "HTML" /
    "MarkdownV2" para permitir negritas/monoespaciado en el mensaje
    (ej. resúmenes con mejor formato). Parámetro opcional y aditivo -
    quien no lo pase sigue mandando texto plano exactamente igual que antes.

    Devuelve el código de estado HTTP si se envió, o None si falló
    (nunca lanza una excepción hacia quien la llama).
    """

    payload = {"chat_id": CHAT_ID, "text": mensaje}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        respuesta = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        return respuesta.status_code

    except Exception:
        logger.exception("Error enviando mensaje de Telegram")
        return None