"""
Chequeo manual de indicadores técnicos cripto contra la API pública real
de Binance. Solo lectura de datos de mercado, sin API key.

Uso: python -m scripts.check_crypto_indicators
"""

from app.indicators.crypto_indicators import calcular_indicadores_multi_timeframe

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]

COLUMNAS_A_MOSTRAR = ["Close", "RSI", "EMA9", "EMA21", "MACD_12_26_9", "ATR"]


def check_crypto_indicators():
    for symbol in SIMBOLOS:
        print(f"\n=== {symbol} ===")
        resultado = calcular_indicadores_multi_timeframe(symbol)

        for interval, data in resultado.items():
            ultima = data.iloc[-1]
            valores = " | ".join(
                f"{col}:{ultima[col]:.2f}" if pd_isnumber(ultima.get(col)) else f"{col}:N/D"
                for col in COLUMNAS_A_MOSTRAR
            )
            print(f"{interval} @ {data.index[-1]} -> {valores}")


def pd_isnumber(valor):
    try:
        return valor is not None and valor == valor and float(valor) is not None
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    check_crypto_indicators()
