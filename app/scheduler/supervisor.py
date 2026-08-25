"""
Supervisor genérico para correr un scheduler en un hilo con reintentos
limitados (Épica 6). Antes de esto, run_all.py's _iniciar_scheduler
atrapaba cualquier excepción una sola vez, la logueaba, y el hilo
simplemente terminaba - el scheduler de acciones dejaba de correr para
siempre, en silencio, mientras el bot de Telegram (en otro hilo) seguía
respondiendo y el servicio se veía sano.

run_supervised() reintenta con espera creciente (nunca fija, para no
martillar lo que sea que esté fallando - típicamente una API externa) y
nunca reintenta para siempre: al agotar max_restarts envía exactamente
una escalación por Telegram y deja de intentar. Ese tope y esa
escalación son el cambio de observabilidad más importante de todo este
blueprint - sin ellos, un scheduler roto sigue siendo invisible, solo
que ahora con más líneas de log.
"""

import time
from typing import Callable

from loguru import logger

from app.services.telegram_service import enviar_mensaje_telegram

_CAP_ESPERA_SEGUNDOS = 30 * 60  # 30 minutos, tope superior del backoff


def _escalar(name: str, excepcion: Exception, intentos_totales: int) -> None:
    mensaje = f"""
🆘 ROBOTINAIA - {name} DETENIDO

Se agotaron los {intentos_totales} reintentos.
Última excepción: {type(excepcion).__name__}: {excepcion}

El proceso sigue corriendo (Telegram y los demás schedulers no se ven
afectados), pero {name} dejó de ejecutarse y no se reintentará más sin
intervención manual.
"""
    codigo = enviar_mensaje_telegram(mensaje)
    logger.critical(
        f"{name}: escalación enviada por Telegram tras {intentos_totales} "
        f"intentos (código: {codigo})"
    )


def run_supervised(
    target: Callable,
    name: str,
    max_restarts: int = 5,
    backoff_base_seconds: int = 30,
) -> None:
    """
    Corre `target()` hasta que retorne sin lanzar excepción, o hasta
    agotar `max_restarts` intentos. Entre intentos fallidos espera
    `backoff_base_seconds * 2 ** (intento - 1)` segundos, con un tope de
    30 minutos, para no reintentar en un loop apretado.

    Al agotar los intentos, envía exactamente una alerta por Telegram
    (nunca reintenta para siempre en silencio) y retorna.
    """
    for intento in range(1, max_restarts + 1):
        try:
            target()
            return
        except Exception as excepcion:
            logger.exception(f"{name}: intento {intento}/{max_restarts} falló")

            if intento >= max_restarts:
                _escalar(name, excepcion, intento)
                return

            espera = min(backoff_base_seconds * (2 ** (intento - 1)), _CAP_ESPERA_SEGUNDOS)
            time.sleep(espera)
