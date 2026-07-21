import yfinance as yf
import pandas_ta as ta

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

macd = ta.macd(
    data["Close"]
)

data = data.join(macd)

print("=" * 70)

print(
    data[
        [
            "Close",
            "MACD_12_26_9",
            "MACDs_12_26_9",
            "MACDh_12_26_9"
        ]
    ].tail(10)
)

print("=" * 70)

ultimo = data.iloc[-1]

if ultimo["MACD_12_26_9"] > ultimo["MACDs_12_26_9"]:
    print("SENAL MACD: ALCISTA")
else:
    print("SENAL MACD: BAJISTA")