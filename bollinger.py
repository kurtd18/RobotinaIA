import yfinance as yf
import pandas_ta as ta

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

bb = ta.bbands(
    data["Close"],
    length=20
)

print("=" * 70)
print(bb.columns)
print("=" * 70)