import time
import subprocess
import schedule
import datetime
import sys


def ejecutar_robotina():

    ahora = datetime.datetime.now()

    if (
        ahora.hour >= 9 and
        ahora.hour < 17
    ):

        print("=" * 80)
        print(f"Ejecutando RobotinaIA: {ahora}")
        print("=" * 80)

        subprocess.run(
            [
                sys.executable,
                "scoring.py"
            ]
        )

        print("=" * 80)
        print("FIN DE EJECUCION")
        print("=" * 80)

    else:

        print(
            f"Fuera de horario: {ahora}"
        )


schedule.every(15).minutes.do(
    ejecutar_robotina
)

print("RobotinaIA V4")
print(f"Python utilizado: {sys.executable}")

ejecutar_robotina()

while True:

    schedule.run_pending()

    time.sleep(1)