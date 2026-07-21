import yfinance as yf
import pandas as pd


class TechnicalIndicators:

    @staticmethod
    def calculate_rsi(symbol: str, period: int = 14):

        try:

            ticker = yf.Ticker(symbol)
            data = ticker.history(period="3mo")

            if data.empty:
                return None

            delta = data["Close"].diff()

            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            avg_gain = gain.rolling(period).mean()
            avg_loss = loss.rolling(period).mean()

            rs = avg_gain / avg_loss

            rsi = 100 - (100 / (1 + rs))

            return round(float(rsi.iloc[-1]), 2)

        except Exception as error:

            print(f"Error calculando RSI: {error}")
            return None

    @staticmethod
    def get_rsi_status(rsi: float):

        if rsi is None:
            return "NO DISPONIBLE"

        if rsi >= 70:
            return "SOBRECOMPRA"

        if rsi <= 30:
            return "SOBREVENTA"

        return "NEUTRAL"

    @staticmethod
    def calculate_sma(symbol: str, period: int = 20):

        try:

            ticker = yf.Ticker(symbol)
            data = ticker.history(period="6mo")

            if data.empty:
                return None

            sma = data["Close"].rolling(period).mean()

            return round(float(sma.iloc[-1]), 2)

        except Exception as error:

            print(f"Error calculando SMA: {error}")
            return None

    @staticmethod
    def calculate_ema(symbol: str, period: int = 20):

        try:

            ticker = yf.Ticker(symbol)
            data = ticker.history(period="6mo")

            if data.empty:
                return None

            ema = data["Close"].ewm(span=period).mean()

            return round(float(ema.iloc[-1]), 2)

        except Exception as error:

            print(f"Error calculando EMA: {error}")
            return None


if __name__ == "__main__":

    print("=" * 60)
    print("INDICADORES TÉCNICOS")
    print("=" * 60)

    symbol = "AAPL"

    rsi = TechnicalIndicators.calculate_rsi(symbol)
    sma = TechnicalIndicators.calculate_sma(symbol)
    ema = TechnicalIndicators.calculate_ema(symbol)

    print(f"Activo      : {symbol}")
    print(f"RSI         : {rsi}")
    print(f"Estado RSI  : {TechnicalIndicators.get_rsi_status(rsi)}")
    print(f"SMA(20)     : {sma}")
    print(f"EMA(20)     : {ema}")

    print("=" * 60)