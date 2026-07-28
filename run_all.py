"""
Punto de entrada combinado para despliegue en la nube (Railway).

Corre el scheduler (main.py) y el bot de Telegram (telegram_bot.py) en el
mismo proceso, compartiendo la misma base de datos - necesario porque en
Railway cada servicio tiene su propio volumen de almacenamiento por
separado, así que si corrieran como dos servicios distintos no verían
los mismos datos.

Para desarrollo local, se puede seguir usando main.py y telegram_bot.py
por separado (dos terminales), como hasta ahora.
"""

import threading

from loguru import logger

import main as scheduler_module
import telegram_bot


def _iniciar_scheduler():
    try:
        scheduler_module.main()
    except Exception:
        logger.exception("El scheduler se detuvo por un error inesperado")


def _iniciar_bot():
    try:
        telegram_bot.main()
    except Exception:
        logger.exception("El bot de Telegram se detuvo por un error inesperado")


if __name__ == "__main__":
    logger.info("Iniciando RobotinaIA (scheduler + bot en un solo proceso)...")

    hilo_scheduler = threading.Thread(target=_iniciar_scheduler, daemon=True)
    hilo_scheduler.start()

    try:
        # El bot corre en el hilo principal (python-telegram-bot necesita el
        # hilo principal para manejar señales de apagado correctamente).
        _iniciar_bot()
    except KeyboardInterrupt:
        logger.info("RobotinaIA detenido por el usuario")