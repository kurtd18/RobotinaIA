
import time
import subprocess
import schedule
import sys

import init_db

from datetime import datetime
from zoneinfo import ZoneInfo

from signal_manager import expire_old_signals


def ejecutar_robotina():

    try:

        ahora = datetime.now(
            ZoneInfo("America/Bogota")
        )

        if 9 <= ahora.hour < 17:

            print("=" * 80)
            print(f"Ejecutando RobotinaIA: {ahora}")
            print("=" * 80)

            subprocess.run(
                [
                    sys.executable,
                    "scoring.py"
                ],
                check=False
            )

            expire_old_signals()

            print("=" * 80)
            print("FIN DE EJECUCIÓN")
            print("=" * 80)

        else:

            print(f"Fuera de horario: {ahora}")

    except Exception as e:

        print(f"ERROR: {e}")


schedule.every(15).minutes.do(ejecutar_robotina)

print("=" * 80)
print("RobotinaIA V7")
print(f"Python: {sys.executable}")
print("=" * 80)

ejecutar_robotina()

while True:

    schedule.run_pending()
    time.sleep(1)