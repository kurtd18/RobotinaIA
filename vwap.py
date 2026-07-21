import yfinance as yf
import pandas_ta as ta

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

data["VWAP"] = ta.vwap(
    high=data["High"],
    low=data["Low"],
    close=data["Close"],
    volume=data["Volume"]
)

print("=" * 60)

print(
    data[
        ["Close", "VWAP"]
    ].tail(10)
)

print("=" * 60)

ultimo = data.iloc[-1]

if ultimo["Close"] > ultimo["VWAP"]:
    print("SENAL VWAP: ALCISTA")
else:
    print("SENAL VWAP: BAJISTA")