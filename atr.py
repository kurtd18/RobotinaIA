import yfinance as yf
import pandas_ta as ta

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

data["ATR"] = ta.atr(
    high=data["High"],
    low=data["Low"],
    close=data["Close"],
    length=14
)

print("=" * 60)

print(
    data[
        ["Close", "ATR"]
    ].tail(10)
)

print("=" * 60)

ultimo = data.iloc[-1]

atr_actual = ultimo["ATR"]

print(f"ATR ACTUAL: {atr_actual:.2f}")

if atr_actual > 30:
    print("SENAL ATR: VOLATILIDAD ALTA")
else:
    print("SENAL ATR: VOLATILIDAD BAJA")