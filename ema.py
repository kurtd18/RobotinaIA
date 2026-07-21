import yfinance as yf
import pandas_ta as ta

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

data["EMA9"] = ta.ema(
    data["Close"],
    length=9
)

data["EMA21"] = ta.ema(
    data["Close"],
    length=21
)

print("=" * 60)

print(
    data[
        ["Close", "EMA9", "EMA21"]
    ].tail(10)
)

print("=" * 60)

ultimo = data.iloc[-1]

if ultimo["EMA9"] > ultimo["EMA21"]:
    print("SENAL: ALCISTA")
else:
    print("SENAL: BAJISTA")