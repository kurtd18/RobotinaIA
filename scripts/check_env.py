"""
Chequeo manual de que las variables de entorno necesarias están configuradas.

No imprime los valores reales (serían credenciales sensibles) - solo
confirma si cada una está presente o falta.

Uso: python scripts/check_env.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

VARIABLES_REQUERIDAS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GEMINI_API_KEY",
]


def check_env():
    print("=" * 50)
    print("CHEQUEO DE VARIABLES DE ENTORNO")
    print("=" * 50)

    for variable in VARIABLES_REQUERIDAS:
        valor = os.getenv(variable)
        estado = "OK (configurada)" if valor else "FALTA"
        print(f"{variable:25} {estado}")

    print("=" * 50)


if __name__ == "__main__":
    check_env()