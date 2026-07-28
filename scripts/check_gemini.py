"""
Chequeo manual de conectividad con la API de Gemini.

No forma parte de ninguna funcionalidad del sistema - solo confirma
que la API key configurada funciona.

Uso: python scripts/check_gemini.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

MODEL = "gemini-2.0-flash"


def check_gemini():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("GEMINI_API_KEY no está configurada en el .env")
        return

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents="Di hola y confirma que Gemini esta funcionando.",
        )
        print(response.text)
    except Exception as e:
        print(f"Error conectando con Gemini: {e}")


if __name__ == "__main__":
    check_gemini()