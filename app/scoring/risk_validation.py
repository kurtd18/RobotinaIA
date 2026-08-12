"""
Validación de relación riesgo/beneficio (R:R) del CryptoScoringEngine.

Regla explícita (no hay todavía una estrategia de entrada/salida
definida en el proyecto, así que se usa una convención simple y
documentada, no arbitraria):
- Distancia de riesgo (stop) = ATR(1h) * 1.5, medida desde el precio actual.
- Distancia de beneficio (target) = distancia hasta la resistencia (para
  LONG) o soporte (para SHORT) más cercana, usando el máximo/mínimo de
  las últimas 20 velas de 4h (misma ventana que soporte_resistencia del
  score técnico).
- R:R = distancia_target / distancia_stop.

Si no se puede calcular (datos insuficientes), NO se asume que cumple
el mínimo - la señal candidata queda forzada a NO_OPERAR en el motor
principal (fail-safe, nunca se asume una relación riesgo/beneficio que
no se pudo verificar).
"""

from loguru import logger

from app.indicators.technical_indicators import calcular_atr
from app.providers.binance_provider import BinanceProvider, BinanceProviderError

RATIO_MINIMO = 1.5
MULTIPLICADOR_ATR = 1.5
LOOKBACK_ESTRUCTURA = 20


def calcular_risk_reward(symbol: str, direccion: str, provider: BinanceProvider = None) -> dict:
    """
    direccion: "LONG" o "SHORT" (la señal candidata que se está validando)

    Devuelve:
    {
        "disponible": bool,
        "entry": float | None,
        "stop": float | None,
        "target": float | None,
        "distancia_stop": float | None,
        "distancia_target": float | None,
        "ratio": float | None,
        "cumple_minimo": bool,
    }
    """
    provider = provider or BinanceProvider()

    try:
        data_1h = provider.get_ohlcv(symbol, "1h", num_velas=50)
        data_4h = provider.get_ohlcv(symbol, "4h", num_velas=LOOKBACK_ESTRUCTURA + 1)
    except BinanceProviderError as e:
        logger.error(f"No se pudo calcular R:R para {symbol}: {e}")
        return _no_disponible()

    entry = float(data_1h["Close"].iloc[-1])
    atr = calcular_atr(data_1h).iloc[-1]

    if atr is None or atr != atr or len(data_4h) < LOOKBACK_ESTRUCTURA:
        logger.warning(f"Datos insuficientes para calcular R:R de {symbol}")
        return _no_disponible()

    distancia_stop = float(atr) * MULTIPLICADOR_ATR
    ventana_4h = data_4h.iloc[-LOOKBACK_ESTRUCTURA:]

    if direccion == "LONG":
        target = float(ventana_4h["High"].max())
        stop = entry - distancia_stop
        distancia_target = target - entry
    elif direccion == "SHORT":
        target = float(ventana_4h["Low"].min())
        stop = entry + distancia_stop
        distancia_target = entry - target
    else:
        raise ValueError(f"Dirección '{direccion}' no soportada, usa LONG o SHORT")

    if distancia_stop <= 0 or distancia_target <= 0:
        logger.warning(f"R:R de {symbol} no calculable: distancias inválidas (target ya superado)")
        return _no_disponible()

    ratio = distancia_target / distancia_stop

    resultado = {
        "disponible": True,
        "entry": entry,
        "stop": stop,
        "target": target,
        "distancia_stop": distancia_stop,
        "distancia_target": distancia_target,
        "ratio": ratio,
        "cumple_minimo": ratio >= RATIO_MINIMO,
    }
    logger.info(f"OK: R:R {symbol} {direccion} = {ratio:.2f} (mínimo {RATIO_MINIMO})")
    return resultado


def _no_disponible() -> dict:
    return {
        "disponible": False,
        "entry": None, "stop": None, "target": None,
        "distancia_stop": None, "distancia_target": None,
        "ratio": None, "cumple_minimo": False,  # fail-safe: sin datos, no se asume que cumple
    }
