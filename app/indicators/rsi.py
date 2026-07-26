import yfinance as yf
import pandas_ta as ta

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

data["RSI"] = ta.rsi(
    data["Close"],
    length=14
)

print("=" * 50)
print(
    data[
        ["Close", "RSI"]
    ].tail(10)
)
print("=" * 50)