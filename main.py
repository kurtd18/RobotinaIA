"""
Punto de entrada de RobotinaIA.
Ejecuta la estrategia RSI(2) de Connors cada 30 minutos, de 8:00am a
5:00pm (America/Bogota).
"""

import sys
import time

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

import init_db

from app.alerts.portfolio_alerts import revisar_alertas_portafolio
from app.core.settings import Settings
from app.strategies.rsi2_connors import ejecutar_rsi2_connors


logger.add(
    "logs/robotina_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="14 days",
    level="INFO",
)


def ejecutar_robotina() -> None:
    """Corre un ciclo completo: RSI(2) de Connors + alertas de portafolio.

    Corre cada 30 minutos, pero SOLO dentro de la ventana de horario
    configurada (HORA_INICIO_REVISION a HORA_FIN_REVISION, ver Settings)
    - fuera de esa ventana, el ciclo se salta sin hacer nada. La
    librería `schedule` no soporta nativamente "cada N minutos, pero
    solo entre estas horas", así que el filtro se hace aquí adentro.

    Nota: como el RSI(2)/SMA200 usa velas DIARIAS, y el mercado sigue
    abierto durante la ventana de revisión, la vela de "hoy" todavía se
    está formando en cada revisión intradía - una señal que aparece a
    media mañana podría no sostenerse hasta el cierre. Es información
    en vivo, no el cierre confirmado del día.
    """

    ahora = datetime.now(ZoneInfo("America/Bogota"))

    dentro_de_horario = Settings.HORA_INICIO_REVISION <= ahora.strftime("%H:%M") <= Settings.HORA_FIN_REVISION
    if not dentro_de_horario:
        logger.info(f"Fuera de horario de revisión ({ahora.strftime('%H:%M')}), se salta este ciclo")
        return

    logger.info("=" * 80)
    logger.info(f"Ejecutando RobotinaIA: {ahora}")
    logger.info("=" * 80)

    try:
        ejecutar_rsi2_connors()
    except Exception:
        logger.exception("Error ejecutando la estrategia RSI(2) Connors")

    try:
        revisar_alertas_portafolio()
    except Exception:
        logger.exception("Error revisando alertas de portafolio")

    logger.info("=" * 80)
    logger.info("FIN DE EJECUCIÓN")
    logger.info("=" * 80)


def main() -> None:
    logger.info("=" * 80)
    logger.info(f"{Settings.APP_NAME} - Iniciando scheduler")
    logger.info(f"Python: {sys.executable}")
    logger.info(
        f"Revisión cada {Settings.INTERVALO_REVISION_MINUTOS} min, "
        f"de {Settings.HORA_INICIO_REVISION} a {Settings.HORA_FIN_REVISION} (America/Bogota)"
    )
    logger.info("=" * 80)

    init_db.init_db()

    ejecutar_robotina()

    import schedule

    schedule.every(Settings.INTERVALO_REVISION_MINUTOS).minutes.do(ejecutar_robotina)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("RobotinaIA detenido por el usuario")


if __name__ == "__main__":
    main()