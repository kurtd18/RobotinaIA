import os
import requests
import datetime
import yfinance as yf
import pandas_ta as ta

from dotenv import load_dotenv

from database import (
    guardar_senal,
    existe_senal_pendiente
)

load_dotenv()

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

ACTIVOS = [

    "MINEROS.CL",
    "ECOPETROL.CL",

    "BTC-USD",
    "ETH-USD",
    "SOL-USD",

    "AAPL",
    "NVDA"

]

resultados = []

print("=" * 80)
print("ROBOTINAIA V5.2")
print(
    f"Hora: {datetime.datetime.now()}"
)
print("=" * 80)

for activo in ACTIVOS:

    try:

        score = 0

        data = yf.Ticker(
            activo
        ).history(
            period="5d",
            interval="5m"
        )

        if data.empty:

            print(
                f"{activo}: SIN DATOS"
            )

            continue

        # RSI

        data["RSI"] = ta.rsi(
            data["Close"],
            length=14
        )

        # EMA

        data["EMA9"] = ta.ema(
            data["Close"],
            length=9
        )

        data["EMA21"] = ta.ema(
            data["Close"],
            length=21
        )

        # VWAP

        data["VWAP"] = ta.vwap(
            data["High"],
            data["Low"],
            data["Close"],
            data["Volume"]
        )

        # MACD

        macd = ta.macd(
            data["Close"]
        )

        data = data.join(
            macd
        )

        # ATR

        data["ATR"] = ta.atr(
            data["High"],
            data["Low"],
            data["Close"],
            length=14
        )

        # Volumen promedio

        data["VOL_AVG"] = (
            data["Volume"]
            .rolling(20)
            .mean()
        )

        ultimo = data.iloc[-1]

        # SCORE

        if ultimo["RSI"] > 50:

            score += 10

        if ultimo["EMA9"] > ultimo["EMA21"]:

            score += 15

        if ultimo["Close"] > ultimo["VWAP"]:

            score += 30

        if (
            ultimo["MACD_12_26_9"]
            >
            ultimo["MACDs_12_26_9"]
        ):

            score += 10

        if (
            ultimo["Volume"]
            >
            ultimo["VOL_AVG"]
        ):

            score += 25

        if ultimo["ATR"] > 30:

            score += 5

        # Peso temporal Bollinger

        score += 5

        resultados.append(
            (
                activo,
                score
            )
        )

        print(
            f"{activo:15}"
            f" -> SCORE: {score}"
        )

    except Exception as e:

        print(
            f"{activo}: ERROR"
        )

        print(e)

print()
print("=" * 80)
print("TOP OPORTUNIDADES")
print("=" * 80)

for activo, score in sorted(
    resultados,
    key=lambda x: x[1],
    reverse=True
):

    print(
        f"{activo:15} {score}"
    )

print()
print("=" * 80)
print(
    "SENALES MAYORES O IGUALES A 80"
)
print("=" * 80)

for activo, score in sorted(
    resultados,
    key=lambda x: x[1],
    reverse=True
):

    if score >= 80:

        try:

            if existe_senal_pendiente(
                activo
            ):

                print(
                    f"{activo}"
                    " -> YA EXISTE UNA "
                    "SENAL PENDIENTE"
                )

                continue

            data = yf.Ticker(
                activo
            ).history(
                period="5d",
                interval="5m"
            )

            if data.empty:

                continue

            precio = float(
                data.iloc[-1]["Close"]
            )

            guardar_senal(

                str(
                    datetime.datetime.now()
                ),

                activo,

                score,

                precio
            )

            mensaje = f"""
ROBOTINAIA

OPORTUNIDAD DETECTADA

Activo:
{activo}

Score:
{score}/100

Precio Entrada:
{precio:.2f}

Probabilidad:
ALTA

Horizonte:
5-15 minutos.

Hora:
{datetime.datetime.now()}
"""

            respuesta = requests.post(

                f"https://api.telegram.org/"
                f"bot{TOKEN}/sendMessage",

                json={

                    "chat_id": CHAT_ID,

                    "text": mensaje
                }

            )

            print(

                f"{activo}"

                f" -> TELEGRAM "

                f"({respuesta.status_code})"

            )

        except Exception as e:

            print(
                f"{activo}: ERROR"
            )

            print(e)

print("=" * 80)
print("PROCESO FINALIZADO")
print("=" * 80)