import os
import requests
import yfinance as yf
from ollama import chat
from dotenv import load_dotenv

load_dotenv()

# Obtener informacion de MINEROS
accion = yf.Ticker("MINEROS.CL")

precio = accion.info["currentPrice"]
variacion = accion.info["regularMarketChangePercent"]
maximo = accion.info["dayHigh"]
minimo = accion.info["dayLow"]

prompt = f"""
Actua como RobotinaIA.

Analiza la siguiente informacion:

- Accion: MINEROS
- Precio actual: {precio} COP
- Variacion diaria: {variacion:.2f}%
- Maximo del dia: {maximo}
- Minimo del dia: {minimo}

Entrega:
1. Resumen ejecutivo.
2. Nivel de riesgo (Bajo, Medio o Alto).
3. Recomendacion (Comprar, Mantener o Vender).
"""

response = chat(
    model="llama3.1",
    messages=[
        {
            "role": "user",
            "content": prompt
        }
    ]
)

mensaje = response["message"]["content"]

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": mensaje
    }
)

print(mensaje)