"""
Indicadores técnicos para cripto (BTC/USDT, ETH/USDT), multi-timeframe.

Fase 2 de RobotinaIA Crypto: solo calcula y expone valores crudos de
indicadores (RSI, EMA9/21, VWAP, MACD, ATR, Bollinger, momentum,
volumen promedio) por timeframe. No decide nada ni genera señales -
eso es una fase posterior (scoring).

Reutiliza app/indicators/technical_indicators.py (compartido con la
estrategia de acciones) sobre los DataFrames OHLCV que entrega
BinanceProvider, en vez de duplicar el cálculo de indicadores.
"""

from loguru import logger

from app.indicators.technical_indicators import agregar_todos_los_indicadores
from app.providers.binance_provider import BinanceProvider, BinanceProviderError

TIMEFRAMES = ("15m", "1h", "4h")

# Velas mínimas para que EMA21/MACD(26,9)/Bollinger(20) tengan suficiente
# historia y no queden en None por falta de datos.
VELAS_POR_DEFECTO = 100


def calcular_indicadores(symbol: str, interval: str, provider: BinanceProvider = None,
                          num_velas: int = VELAS_POR_DEFECTO):
    """
    Devuelve el DataFrame OHLCV de `symbol`/`interval` con las columnas
    de indicadores técnicos agregadas (ver agregar_todos_los_indicadores).
    """
    provider = provider or BinanceProvider()

    logger.info(f"Calculando indicadores técnicos {symbol} {interval}...")
    ohlcv = provider.get_ohlcv(symbol, interval, num_velas=num_velas)

    data = agregar_todos_los_indicadores(ohlcv)
    logger.info(f"OK: indicadores calculados para {symbol} {interval} ({len(data)} velas)")
    return data


def calcular_indicadores_multi_timeframe(symbol: str, provider: BinanceProvider = None,
                                          num_velas: int = VELAS_POR_DEFECTO):
    """
    Devuelve un dict {timeframe: DataFrame con indicadores} para los tres
    timeframes soportados (15m, 1h, 4h) de un mismo símbolo.

    Si un timeframe falla (ej. sin datos), se registra el error y se
    excluye del resultado en vez de tumbar los demás timeframes.
    """
    provider = provider or BinanceProvider()
    resultado = {}

    for interval in TIMEFRAMES:
        try:
            resultado[interval] = calcular_indicadores(symbol, interval, provider, num_velas)
        except BinanceProviderError as e:
            logger.error(f"No se pudieron calcular indicadores {symbol} {interval}: {e}")

    return resultado
