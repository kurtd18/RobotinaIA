import yfinance as yf

activo = "MINEROS.CL"

data = yf.Ticker(activo).history(
    period="5d",
    interval="5m"
)

print(data.tail())