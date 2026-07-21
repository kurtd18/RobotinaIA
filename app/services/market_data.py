import yfinance as yf


class MarketDataProvider:

    @staticmethod
    def get_stock_price(symbol: str):

        # Soporte temporal para acciones de la BVC
        if symbol.upper() == "MINEROS":
            return 15680.00

        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d")

            if data.empty:
                return None

            return round(float(data["Close"].iloc[-1]), 2)

        except Exception as error:
            print(f"❌ Error obteniendo precio de {symbol}: {error}")
            return None

    @staticmethod
    def get_stock_info(symbol: str):

        # Información temporal para MINEROS
        if symbol.upper() == "MINEROS":
            return {
                "symbol": "MINEROS",
                "name": "Mineros S.A.",
                "price": 15680.00,
                "currency": "COP"
            }

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            return {
                "symbol": symbol,
                "name": info.get("longName", "No disponible"),
                "price": info.get("currentPrice", "No disponible"),
                "currency": info.get("currency", "USD")
            }

        except Exception as error:
            print(f"❌ Error obteniendo información: {error}")
            return None


if __name__ == "__main__":

    print("=" * 60)
    print("PRUEBA DEL PROVEEDOR DE DATOS")
    print("=" * 60)

    symbols = [
        "AAPL",
        "MSFT",
        "GOOGL",
        "SPY",
        "BTC-USD",
        "MINEROS"
    ]

    for symbol in symbols:

        info = MarketDataProvider.get_stock_info(symbol)

        if info:

            print(f"Activo   : {info['symbol']}")
            print(f"Nombre   : {info['name']}")
            print(f"Precio   : {info['price']}")
            print(f"Moneda   : {info['currency']}")
            print("-" * 60)