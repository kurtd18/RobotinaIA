import os
import datetime
import requests
import yfinance as yf
import pandas_ta as ta

from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from database import (
    guardar_senal,
    existe_senal_pendiente
)

# ==========================================================
# CONFIGURACIÓN
# ==========================================================

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ACTIVOS = [
    "MINEROS.CL",
    "ECOPETROL.CL",
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "AAPL",
    "NVDA"
]

ahora = datetime.datetime.now(
    ZoneInfo("America/Bogota")
)

resultados = []

print("=" * 80)
print("ROBOTINAIA V6.0")
print(f"Hora Colombia: {ahora}")
print("=" * 80)


# ==========================================================
# FUNCIONES
# ==========================================================

def calcular_score(data):

    score = 0

    data["RSI"] = ta.rsi(data["Close"], length=14)

    data["EMA9"] = ta.ema(data["Close"], length=9)
    data["EMA21"] = ta.ema(data["Close"], length=21)

    data["VWAP"] = ta.vwap(
        data["High"],
        data["Low"],
        data["Close"],
        data["Volume"]
    )

    macd = ta.macd(data["Close"])
    data = data.join(macd)

    data["ATR"] = ta.atr(
        data["High"],
        data["Low"],
        data["Close"],
        length=14
    )

    data["VOL_AVG"] = (
        data["Volume"]
        .rolling(20)
        .mean()
    )

    ultimo = data.iloc[-1]

    if ultimo["RSI"] > 50:
        score += 10

    if ultimo["EMA9"] > ultimo["EMA21"]:
        score += 15

    if ultimo["Close"] > ultimo["VWAP"]:
        score += 30

    if ultimo["MACD_12_26_9"] > ultimo["MACDs_12_26_9"]:
        score += 10

    if ultimo["Volume"] > ultimo["VOL_AVG"]:
        score += 25

    if ultimo["ATR"] > 30:
        score += 5

    # Peso temporal
    score += 5

    return score, float(ultimo["Close"])


def enviar_telegram(activo, score, precio):

    mensaje = f"""
🤖 ROBOTINAIA

✅ OPORTUNIDAD DETECTADA

📈 Activo: {activo}

⭐ Score: {score}/100

💲 Precio: {precio:.2f}

🕒 Hora: {ahora}

🎯 Acción sugerida:
Revisar la entrada antes de comprar.
"""

    respuesta = requests.post(

        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

        json={
            "chat_id": CHAT_ID,
            "text": mensaje
        }

    )

    print(f"{activo} -> TELEGRAM ({respuesta.status_code})")


# ==========================================================
# ANALISIS
# ==========================================================

for activo in ACTIVOS:

    try:

        data = yf.Ticker(activo).history(
            period="5d",
            interval="5m"
        )

        if data.empty:

            print(f"{activo}: SIN DATOS")
            continue

        score, precio = calcular_score(data)

        resultados.append({
            "activo": activo,
            "score": score,
            "precio": precio
        })

        print(f"{activo:15} -> SCORE: {score}")

    except Exception as e:

        print(f"{activo}: ERROR")
        print(e)

print()
print("=" * 80)
print("TOP OPORTUNIDADES")
print("=" * 80)

resultados.sort(
    key=lambda x: x["score"],
    reverse=True
)

for r in resultados:

    print(
        f"{r['activo']:15} {r['score']}"
    )

print()
print("=" * 80)
print("SEÑALES MAYORES O IGUALES A 80")
print("=" * 80)

for r in resultados:

    if r["score"] < 80:
        continue

    try:

        if existe_senal_pendiente(r["activo"]):

            print(
                f"{r['activo']} -> YA EXISTE UNA SEÑAL PENDIENTE"
            )

            continue

        guardar_senal(

            str(ahora),

            r["activo"],

            r["score"],

            r["precio"]

        )

        enviar_telegram(

            r["activo"],

            r["score"],

            r["precio"]

        )

    except Exception as e:

        print(f"{r['activo']}: ERROR")
        print(e)

print("=" * 80)
print("PROCESO FINALIZADO")
print("=" * 80)