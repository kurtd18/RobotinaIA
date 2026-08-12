"""
Chequeo manual de BinanceProvider contra la API pública real de Binance.

Solo lee datos públicos de mercado (velas, funding rate, open interest).
No usa API key, no envía ninguna solicitud autenticada, no coloca
órdenes ni toca ninguna cuenta.

Uso: python scripts/check_binance_provider.py
"""

from app.providers.binance_provider import BinanceProvider, BinanceProviderError

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]
INTERVALOS = ["15m", "1h", "4h"]


def check_binance_provider():
    provider = BinanceProvider()

    for symbol in SIMBOLOS:
        print(f"\n=== {symbol} ===")

        for interval in INTERVALOS:
            try:
                df = provider.get_ohlcv(symbol, interval, num_velas=3)
                ultima = df.iloc[-1]
                print(
                    f"OHLCV {interval}: {len(df)} velas | última vela -> "
                    f"O:{ultima['Open']:.2f} H:{ultima['High']:.2f} "
                    f"L:{ultima['Low']:.2f} C:{ultima['Close']:.2f} "
                    f"V:{ultima['Volume']:.2f} @ {df.index[-1]}"
                )
            except BinanceProviderError as e:
                print(f"OHLCV {interval}: ERROR - {e}")

        try:
            funding = provider.get_funding_rate(symbol)
            print(
                f"Funding rate: {funding['funding_rate']:.6f} "
                f"@ {funding['funding_time']}"
            )
        except BinanceProviderError as e:
            print(f"Funding rate: ERROR - {e}")

        try:
            oi = provider.get_open_interest(symbol)
            print(f"Open interest: {oi['open_interest']} @ {oi['time']}")
        except BinanceProviderError as e:
            print(f"Open interest: ERROR - {e}")


if __name__ == "__main__":
    check_binance_provider()
