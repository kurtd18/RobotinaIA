"""
Score de derivados (20 puntos) del CryptoScoringEngine.

Reglas explícitas por métrica:
- funding_rate: > +0.05% => desfavorable (largos sobrecargados, riesgo
  de mean-reversion); < -0.05% => favorable (cortos sobrecargados,
  riesgo de short squeeze); entre medio => neutral. Lectura contrarian,
  estándar en derivados cripto.
- oi_precio_volumen: NO se interpreta el open interest aislado - se
  combina su tendencia con la tendencia de precio (pedido explícito):
    OI subiendo + precio subiendo => favorable (entra dinero nuevo comprando)
    OI subiendo + precio bajando  => desfavorable (entra dinero nuevo vendiendo)
    OI bajando  + precio subiendo => neutral (cierre de cortos / short covering, rally frágil)
    OI bajando  + precio bajando  => neutral (cierre de largos, posible agotamiento bajista)
- long_short_ratio: lectura contrarian sobre el ratio global de cuentas:
  > 1.5 (muchos más largos que cortos) => desfavorable; < 0.7 => favorable;
  entre medio => neutral.
- liquidaciones: dominancia de liquidaciones de cortos (potencial squeeze
  alcista) => favorable; dominancia de liquidaciones de largos =>
  desfavorable; equilibrado o sin liquidaciones recientes => neutral
  (dato válido, no "sin_datos").
"""

from loguru import logger

from app.derivatives.crypto_derivatives import calcular_funding_rate, calcular_open_interest
from app.providers.binance_provider import BinanceProvider, BinanceProviderError
from app.scoring.metric_types import puntaje_categoria

PUNTOS_TOTALES = 20

UMBRAL_FUNDING_ALTO = 0.0005
UMBRAL_FUNDING_BAJO = -0.0005

UMBRAL_LS_RATIO_ALTO = 1.5
UMBRAL_LS_RATIO_BAJO = 0.7

UMBRAL_DOMINANCIA_LIQUIDACIONES = 1.5  # una liquidación domina si es >= 1.5x la otra

FUENTE_BINANCE = "Binance Futures API"


def _senal_funding_rate(funding_rate: float) -> str:
    if funding_rate > UMBRAL_FUNDING_ALTO:
        return "desfavorable"
    if funding_rate < UMBRAL_FUNDING_BAJO:
        return "favorable"
    return "neutral"


def _senal_oi_precio(oi_tendencia: str, precio_tendencia: str) -> str:
    if oi_tendencia == "subiendo" and precio_tendencia == "subiendo":
        return "favorable"
    if oi_tendencia == "subiendo" and precio_tendencia == "bajando":
        return "desfavorable"
    return "neutral"  # OI bajando (short covering o cierre de largos) - ambos casos neutrales


def _senal_long_short_ratio(ratio: float) -> str:
    if ratio > UMBRAL_LS_RATIO_ALTO:
        return "desfavorable"
    if ratio < UMBRAL_LS_RATIO_BAJO:
        return "favorable"
    return "neutral"


def _senal_liquidaciones(ordenes: list[dict]) -> str:
    if not ordenes:
        return "neutral"

    # side="SELL" liquida una posición LARGA; side="BUY" liquida una posición CORTA
    liquidaciones_largos = sum(1 for o in ordenes if o["side"] == "SELL")
    liquidaciones_cortos = sum(1 for o in ordenes if o["side"] == "BUY")

    if liquidaciones_cortos >= liquidaciones_largos * UMBRAL_DOMINANCIA_LIQUIDACIONES and liquidaciones_cortos > 0:
        return "favorable"
    if liquidaciones_largos >= liquidaciones_cortos * UMBRAL_DOMINANCIA_LIQUIDACIONES and liquidaciones_largos > 0:
        return "desfavorable"
    return "neutral"


def _precio_tendencia(provider: BinanceProvider, symbol: str) -> str:
    """Tendencia de precio reciente (4h) para combinar con OI - no
    depende de tocar la lógica de scoring técnico, es una lectura simple
    de cierre reciente vs previo."""
    data = provider.get_ohlcv(symbol, "4h", num_velas=30)
    cierres = data["Close"].tolist()
    mitad = len(cierres) // 2
    previos, recientes = cierres[:mitad], cierres[mitad:]
    promedio_reciente = sum(recientes) / len(recientes)
    promedio_previo = sum(previos) / len(previos)

    if promedio_previo == 0:
        return "estable"
    variacion_pct = (promedio_reciente - promedio_previo) / abs(promedio_previo) * 100
    if variacion_pct > 1.0:
        return "subiendo"
    if variacion_pct < -1.0:
        return "bajando"
    return "estable"


def calcular_score_derivados(symbol: str, provider: BinanceProvider = None) -> dict:
    provider = provider or BinanceProvider()
    metricas = []

    logger.info(f"Calculando score de derivados {symbol}...")

    try:
        fr = calcular_funding_rate(symbol, provider)
        metricas.append({
            "metrica": "funding_rate", "valor": fr["funding_rate_actual"], "unidad": "ratio",
            "timestamp": None, "fuente": FUENTE_BINANCE,
            "senal": _senal_funding_rate(fr["funding_rate_actual"]),
        })
    except BinanceProviderError as e:
        logger.error(f"No se pudo calcular funding rate para score de derivados {symbol}: {e}")
        metricas.append({"metrica": "funding_rate", "valor": None, "unidad": None,
                          "timestamp": None, "fuente": "no disponible", "senal": "sin_datos"})

    try:
        oi = calcular_open_interest(symbol, provider)
        precio_tendencia = _precio_tendencia(provider, symbol)
        metricas.append({
            "metrica": "oi_precio_volumen", "valor": oi["open_interest_actual"], "unidad": "contratos",
            "timestamp": None, "fuente": FUENTE_BINANCE,
            "senal": _senal_oi_precio(oi["open_interest_tendencia"], precio_tendencia),
        })
    except BinanceProviderError as e:
        logger.error(f"No se pudo calcular OI/precio para score de derivados {symbol}: {e}")
        metricas.append({"metrica": "oi_precio_volumen", "valor": None, "unidad": None,
                          "timestamp": None, "fuente": "no disponible", "senal": "sin_datos"})

    try:
        ls_hist = provider.get_long_short_ratio(symbol)
        ratio_actual = ls_hist[-1]["long_short_ratio"]
        metricas.append({
            "metrica": "long_short_ratio", "valor": ratio_actual, "unidad": "ratio",
            "timestamp": ls_hist[-1]["time"], "fuente": FUENTE_BINANCE,
            "senal": _senal_long_short_ratio(ratio_actual),
        })
    except BinanceProviderError as e:
        logger.error(f"No se pudo calcular long/short ratio para score de derivados {symbol}: {e}")
        metricas.append({"metrica": "long_short_ratio", "valor": None, "unidad": None,
                          "timestamp": None, "fuente": "no disponible", "senal": "sin_datos"})

    try:
        liquidaciones = provider.get_liquidation_orders(symbol)
        metricas.append({
            "metrica": "liquidaciones", "valor": len(liquidaciones), "unidad": "órdenes",
            "timestamp": None, "fuente": FUENTE_BINANCE,
            "senal": _senal_liquidaciones(liquidaciones),
        })
    except BinanceProviderError as e:
        logger.error(f"No se pudo calcular liquidaciones para score de derivados {symbol}: {e}")
        metricas.append({"metrica": "liquidaciones", "valor": None, "unidad": None,
                          "timestamp": None, "fuente": "no disponible", "senal": "sin_datos"})

    resultado = puntaje_categoria(metricas, PUNTOS_TOTALES)
    logger.info(f"OK: score derivados {symbol} = {resultado['puntos']}/{PUNTOS_TOTALES}")
    return resultado
