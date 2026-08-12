"""
Score técnico (30 puntos) del CryptoScoringEngine.

Cada timeframe (4h, 1h, 15m) se evalúa por separado con reglas
explícitas por indicador, y se combinan con los pesos: 4H=40%, 1H=40%,
15M=20% (pedido explícitamente, no es un promedio simple entre
timeframes).

Reglas por métrica (dirección: favorable=alcista, desfavorable=bajista):
- estructura_ema: close > EMA20 > EMA50 > EMA200 => favorable (tendencia
  alcista alineada); close < EMA20 < EMA50 < EMA200 => desfavorable;
  cualquier otro orden => neutral (tendencia mixta/lateral).
- rsi: > 55 => favorable (momentum alcista), < 45 => desfavorable, entre
  45-55 => neutral. Convención de momentum (no contrarian), consistente
  con el uso de RSI>50 en scoring.py legacy del proyecto.
- macd: línea MACD > señal => favorable, < señal => desfavorable.
- soporte_resistencia: close por encima del máximo de las últimas N
  velas (excluyendo la actual) => favorable (ruptura de resistencia);
  por debajo del mínimo => desfavorable (ruptura de soporte); dentro del
  rango => neutral.
- volumen: solo confirma dirección de precio, no tiene lectura propia:
  volumen > promedio Y precio subiendo => favorable; volumen > promedio
  Y precio bajando => desfavorable; en otro caso => neutral.
- atr: siempre neutral - es una medida de volatilidad, no de dirección.
  Se conserva para transparencia y para el validador de riesgo, no
  aporta puntos direccionales.
"""

from loguru import logger

from app.indicators.technical_indicators import calcular_atr, calcular_ema, calcular_macd, calcular_rsi
from app.providers.binance_provider import BinanceProvider, BinanceProviderError
from app.scoring.metric_types import puntaje_categoria

PUNTOS_TOTALES = 30

PESOS_TIMEFRAME = {"4h": 0.4, "1h": 0.4, "15m": 0.2}

VELAS_MINIMAS = 250  # suficientes para EMA200 con margen
LOOKBACK_SOPORTE_RESISTENCIA = 20


def _estructura_ema(data) -> str:
    close = data["Close"].iloc[-1]
    ema20 = calcular_ema(data, 20).iloc[-1]
    ema50 = calcular_ema(data, 50).iloc[-1]
    ema200 = calcular_ema(data, 200).iloc[-1]

    if any(v is None or v != v for v in (ema20, ema50, ema200)):
        return "sin_datos"

    if close > ema20 > ema50 > ema200:
        return "favorable"
    if close < ema20 < ema50 < ema200:
        return "desfavorable"
    return "neutral"


def _senal_rsi(data) -> str:
    rsi = calcular_rsi(data).iloc[-1]
    if rsi is None or rsi != rsi:
        return "sin_datos"
    if rsi > 55:
        return "favorable"
    if rsi < 45:
        return "desfavorable"
    return "neutral"


def _senal_macd(data) -> str:
    macd = calcular_macd(data)
    if macd is None or macd.empty:
        return "sin_datos"

    fila = macd.iloc[-1]
    linea = fila.get("MACD_12_26_9")
    señal = fila.get("MACDs_12_26_9")
    if linea is None or señal is None or linea != linea or señal != señal:
        return "sin_datos"

    return "favorable" if linea > señal else "desfavorable"


def _senal_soporte_resistencia(data) -> str:
    if len(data) < LOOKBACK_SOPORTE_RESISTENCIA + 1:
        return "sin_datos"

    ventana = data.iloc[-(LOOKBACK_SOPORTE_RESISTENCIA + 1):-1]
    close = data["Close"].iloc[-1]
    resistencia = ventana["High"].max()
    soporte = ventana["Low"].min()

    if close > resistencia:
        return "favorable"
    if close < soporte:
        return "desfavorable"
    return "neutral"


def _senal_volumen(data) -> str:
    if len(data) < 21:
        return "sin_datos"

    volumen_actual = data["Volume"].iloc[-1]
    volumen_promedio = data["Volume"].iloc[-21:-1].mean()
    precio_subiendo = data["Close"].iloc[-1] > data["Close"].iloc[-2]

    if volumen_actual <= volumen_promedio:
        return "neutral"
    return "favorable" if precio_subiendo else "desfavorable"


def calcular_score_timeframe(symbol: str, interval: str, provider: BinanceProvider = None) -> dict:
    """Evalúa las 6 métricas técnicas de un timeframe y devuelve el
    resultado de puntaje_categoria (fracción 0-1 recuperable como
    puntos/PUNTOS_TOTALES)."""
    provider = provider or BinanceProvider()

    logger.info(f"Calculando score técnico {symbol} {interval}...")
    data = provider.get_ohlcv(symbol, interval, num_velas=VELAS_MINIMAS)
    timestamp = data.index[-1]
    precio = float(data["Close"].iloc[-1])
    fuente = f"Binance Klines API ({interval})"

    atr = calcular_atr(data).iloc[-1]
    atr_valor = float(atr) if atr == atr else None

    metricas = [
        {"metrica": "estructura_ema", "valor": precio, "unidad": "USDT", "timestamp": timestamp,
         "fuente": fuente, "senal": _estructura_ema(data)},
        {"metrica": "rsi", "valor": float(calcular_rsi(data).iloc[-1]), "unidad": "0-100",
         "timestamp": timestamp, "fuente": fuente, "senal": _senal_rsi(data)},
        {"metrica": "macd", "valor": None, "unidad": None, "timestamp": timestamp,
         "fuente": fuente, "senal": _senal_macd(data)},
        {"metrica": "soporte_resistencia", "valor": precio, "unidad": "USDT", "timestamp": timestamp,
         "fuente": fuente, "senal": _senal_soporte_resistencia(data)},
        {"metrica": "volumen", "valor": float(data["Volume"].iloc[-1]), "unidad": "USDT",
         "timestamp": timestamp, "fuente": fuente, "senal": _senal_volumen(data)},
        {"metrica": "atr", "valor": atr_valor, "unidad": "USDT", "timestamp": timestamp,
         "fuente": fuente, "senal": "neutral" if atr_valor is not None else "sin_datos"},
    ]

    resultado = puntaje_categoria(metricas, 1.0)  # fracción 0-1, se combina con pesos después
    resultado["precio"] = precio
    resultado["atr"] = atr_valor
    resultado["timestamp"] = timestamp
    logger.info(
        f"OK: score técnico {symbol} {interval} = "
        f"{(resultado['puntos'] or 0) * 100:.1f}% (disponible={resultado['disponible']})"
    )
    return resultado


def calcular_score_tecnico(symbol: str, provider: BinanceProvider = None) -> dict:
    """
    Combina los 3 timeframes con pesos 4H=40%, 1H=40%, 15M=20%. Si un
    timeframe queda sin datos, su peso se redistribuye proporcionalmente
    entre los timeframes disponibles (no penaliza por falta de datos).
    """
    provider = provider or BinanceProvider()
    por_timeframe = {}

    for interval in PESOS_TIMEFRAME:
        try:
            por_timeframe[interval] = calcular_score_timeframe(symbol, interval, provider)
        except BinanceProviderError as e:
            logger.error(f"No se pudo calcular score técnico {symbol} {interval}: {e}")
            por_timeframe[interval] = {"puntos": None, "disponible": False, "cobertura": 0.0,
                                        "metricas": [], "precio": None, "atr": None, "timestamp": None}

    disponibles = {tf: r for tf, r in por_timeframe.items() if r["disponible"]}

    if not disponibles:
        return {
            "puntos": None, "disponible": False, "cobertura": 0.0,
            "por_timeframe": por_timeframe,
        }

    peso_total_disponible = sum(PESOS_TIMEFRAME[tf] for tf in disponibles)
    fraccion_combinada = sum(
        (PESOS_TIMEFRAME[tf] / peso_total_disponible) * disponibles[tf]["puntos"]
        for tf in disponibles
    )

    return {
        "puntos": round(fraccion_combinada * PUNTOS_TOTALES, 4),
        "disponible": True,
        "cobertura": sum(r["cobertura"] for r in disponibles.values()) / len(disponibles),
        "por_timeframe": por_timeframe,
    }
