"""
Punto de entrada de RobotinaIA.
Ejecuta el ciclo de scoring cada N minutos, 24/7.
"""

import sys
import time

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

import init_db

from app.alerts.portfolio_alerts import revisar_alertas_portafolio
from app.core.settings import Settings
from scoring import ejecutar_scoring
from signal_manager import expire_old_signals


logger.add(
    "logs/robotina_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="14 days",
    level="INFO",
)


def ejecutar_robotina() -> None:
    """Corre un ciclo completo: scoring + expiración de señales pendientes."""

    ahora = datetime.now(ZoneInfo("America/Bogota"))

    logger.info("=" * 80)
    logger.info(f"Ejecutando RobotinaIA: {ahora}")
    logger.info("=" * 80)

    try:
        ejecutar_scoring()
    except Exception:
        logger.exception("Error ejecutando scoring.py")

    try:
        expire_old_signals()
    except Exception:
        logger.exception("Error expirando señales pendientes")

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
    logger.info(f"Intervalo: {Settings.SCAN_INTERVAL_MINUTES} min")
    logger.info("=" * 80)

    init_db.init_db()

    ejecutar_robotina()

    import schedule

    schedule.every(Settings.SCAN_INTERVAL_MINUTES).minutes.do(ejecutar_robotina)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("RobotinaIA detenido por el usuario")


if __name__ == "__main__":
    main()