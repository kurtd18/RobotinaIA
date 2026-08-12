"""
Métricas descriptivas de contexto macro para el análisis cripto: DXY,
rendimiento del Tesoro 10Y, S&P 500 y oro.

Fase 5 de RobotinaIA Crypto: solo calcula y expone valores descriptivos
(valor actual, variación % reciente, tendencia). No genera señales ni un
sub-score - eso es una fase posterior (scoring, 10% del análisis final).
Estos indicadores son de todo el mercado, no específicos de BTC/ETH - se
usan igual para ambos activos.
"""

from loguru import logger

from app.macro.macro_provider import MacroProvider, TICKERS_MACRO

PERIODO_DEFECTO = "1mo"
INTERVALO_DEFECTO = "1d"

UMBRAL_TENDENCIA_PCT = 0.5


def _tendencia(valor_reciente: float, valor_previo: float) -> str:
    if valor_previo == 0:
        return "estable"

    variacion_pct = (valor_reciente - valor_previo) / abs(valor_previo) * 100

    if variacion_pct > UMBRAL_TENDENCIA_PCT:
        return "subiendo"
    if variacion_pct < -UMBRAL_TENDENCIA_PCT:
        return "bajando"
    return "estable"


def _partir_en_mitades(valores):
    mitad = len(valores) // 2
    if mitad == 0:
        return valores, valores
    return valores[:mitad], valores[mitad:]


def calcular_indicador_macro(nombre: str, provider: MacroProvider = None,
                              period: str = PERIODO_DEFECTO, interval: str = INTERVALO_DEFECTO) -> dict:
    """
    Devuelve el estado descriptivo de un indicador macro:
    {"nombre", "ticker", "valor_actual", "variacion_pct", "tendencia"}

    nombre: una de las claves de TICKERS_MACRO ("DXY", "US10Y", "SP500", "GOLD")
    """
    if nombre not in TICKERS_MACRO:
        raise ValueError(f"Indicador '{nombre}' no soportado. Usa uno de: {list(TICKERS_MACRO)}")

    provider = provider or MacroProvider()
    ticker = TICKERS_MACRO[nombre]

    logger.info(f"Calculando indicador macro {nombre} ({ticker})...")
    historico = provider.get_history(ticker, period=period, interval=interval)

    cierres = historico["Close"].tolist()
    previos, recientes = _partir_en_mitades(cierres)
    promedio_reciente = sum(recientes) / len(recientes)
    promedio_previo = sum(previos) / len(previos)

    variacion_pct = (
        (promedio_reciente - promedio_previo) / abs(promedio_previo) * 100
        if promedio_previo != 0 else 0.0
    )

    resultado = {
        "nombre": nombre,
        "ticker": ticker,
        "valor_actual": float(cierres[-1]),
        "variacion_pct": variacion_pct,
        "tendencia": _tendencia(promedio_reciente, promedio_previo),
    }
    logger.info(
        f"OK: {nombre} actual={resultado['valor_actual']:.2f} "
        f"variacion={resultado['variacion_pct']:.2f}% tendencia={resultado['tendencia']}"
    )
    return resultado


def calcular_contexto_macro(provider: MacroProvider = None) -> dict:
    """
    Devuelve el contexto macro completo: un dict {nombre: resultado} para
    todos los indicadores en TICKERS_MACRO. Si uno falla, se registra el
    error y se excluye del resultado en vez de tumbar los demás.
    """
    from app.macro.macro_provider import MacroProviderError

    provider = provider or MacroProvider()
    resultado = {}

    for nombre in TICKERS_MACRO:
        try:
            resultado[nombre] = calcular_indicador_macro(nombre, provider)
        except MacroProviderError as e:
            logger.error(f"No se pudo calcular el indicador macro {nombre}: {e}")

    return resultado
