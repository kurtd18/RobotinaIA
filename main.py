"""
Punto de entrada de RobotinaIA.
Ejecuta la estrategia RSI(2) de Connors una vez al día (velas diarias).
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

    A diferencia del scoring anterior (que corría cada 15 minutos con
    velas de 5 minutos), el RSI(2) de Connors usa velas DIARIAS - se
    corre una vez al día (ver el schedule al final de este archivo), no
    tiene sentido revisarlo más seguido porque el resultado de "hoy" no
    cambia hasta que cierre la vela de mañana. Por la misma razón, ya no
    se llama a expire_old_signals() - esa expiración por tiempo (15
    minutos) tenía sentido para el scoring intradía anterior, no para
    una estrategia que puede mantener una posición abierta varios días.
    """

    ahora = datetime.now(ZoneInfo("America/Bogota"))

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
    logger.info(f"Ejecución diaria a las: {Settings.HORA_EJECUCION_DIARIA} (America/Bogota)")
    logger.info("=" * 80)

    init_db.init_db()

    ejecutar_robotina()

    import schedule

    schedule.every().day.at(Settings.HORA_EJECUCION_DIARIA, "America/Bogota").do(ejecutar_robotina)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("RobotinaIA detenido por el usuario")


if __name__ == "__main__":
    main()