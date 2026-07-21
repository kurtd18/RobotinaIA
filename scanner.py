import yfinance as yf

ACTIVOS = [
    "MINEROS.CL",
    "ECOPETROL.CL",
    "PFBCOLOM.CL",
    "ARGOS.CL",
    "ICOLCAP.CL",
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "AAPL",
    "NVDA"
]

print("=" * 50)
print("ROBOTINAIA SCANNER")
print("=" * 50)

for activo in ACTIVOS:

    try:

        ticker = yf.Ticker(activo)

        info = ticker.info

        print(f"""
Activo: {activo}
Precio: {info.get('currentPrice')}
Variacion: {info.get('regularMarketChangePercent')}
Volumen: {info.get('volume')}
        """)

    except Exception as e:

        print(f"ERROR: {activo}")
        print(e)

print("=" * 50)