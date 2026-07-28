"""
Indicadores técnicos reutilizables.

Reciben un DataFrame de OHLCV con el mismo formato que devuelve
yfinance con .history() (columnas: Open, High, Low, Close, Volume).
"""

import pandas_ta as ta


def calcular_rsi(data, length=14):
    return ta.rsi(data["Close"], length=length)


def calcular_ema(data, length):
    return ta.ema(data["Close"], length=length)


def calcular_vwap(data):
    return ta.vwap(data["High"], data["Low"], data["Close"], data["Volume"])


def calcular_macd(data):
    return ta.macd(data["Close"])


def calcular_atr(data, length=14):
    return ta.atr(data["High"], data["Low"], data["Close"], length=length)


def calcular_momentum(data, length=14):
    return ta.mom(data["Close"], length=length)


def calcular_volumen_promedio(data, ventana=20):
    return data["Volume"].rolling(ventana).mean()


def calcular_bollinger(data, length=20):
    return ta.bbands(data["Close"], length=length)


def agregar_todos_los_indicadores(data):
    """Agrega todas las columnas de indicadores técnicos a una copia del DataFrame."""

    data = data.copy()

    data["RSI"] = calcular_rsi(data)
    data["EMA9"] = calcular_ema(data, 9)
    data["EMA21"] = calcular_ema(data, 21)
    data["VWAP"] = calcular_vwap(data)
    data["MOM14"] = calcular_momentum(data)

    macd = calcular_macd(data)
    if macd is not None:
        data = data.join(macd)
    else:
        # No hay suficientes datos para calcular MACD (activo de baja
        # liquidez, pocas velas en la ventana). Se deja vacío en vez de
        # tronar; calcular_score lo trata como "condición no cumplida".
        data["MACD_12_26_9"] = None
        data["MACDh_12_26_9"] = None
        data["MACDs_12_26_9"] = None

    bb = calcular_bollinger(data)
    if bb is not None:
        data = data.join(bb)
    else:
        data["BBU_20_2.0_2.0"] = None

    data["ATR"] = calcular_atr(data)
    data["VOL_AVG"] = calcular_volumen_promedio(data)

    return data