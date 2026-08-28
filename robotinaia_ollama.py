import os
import requests
from ollama import chat
from dotenv import load_dotenv

load_dotenv()

print("Consultando a Llama 3.1...")

response = chat(
    model="llama3.1",
    messages=[
        {
            "role": "user",
            "content": "Actua como RobotinaIA y analiza la accion MINEROS de la Bolsa de Valores de Colombia."
        }
    ]
)

mensaje = response["message"]["content"]

print(mensaje)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

respuesta = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": mensaje
    }
)

print("Estado Telegram:", respuesta.status_code)	
