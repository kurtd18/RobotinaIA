"""
Métricas fundamentales/on-chain de Bitcoin.

Fase 6 de RobotinaIA Crypto: expone cada métrica como
{metrica, valor, unidad, timestamp, fuente, tendencia, estado}.
NO calcula un score 0-100 ni genera señales LONG/SHORT - eso es una
fase posterior. "estado" es una clasificación categórica simple basada
en la tendencia reciente de cada métrica, no un puntaje.

Fuentes: ver docstrings de cada provider en app/onchain/providers/.
Las métricas sin fuente pública gratuita verificada (MVRV, SOPR,
exchange inflows/outflows, comportamiento de holders) se marcan
explícitamente como NO_DISPONIBLE, con valor=None, en vez de inventarse.
"""

from loguru import logger

from app.onchain.providers.blockchain_info_provider import (
    BlockchainInfoProvider,
    BlockchainInfoProviderError,
)

UMBRAL_TENDENCIA_PCT = 1.0

FUENTE_BLOCKCHAIN_INFO = "Blockchain.com Charts API (api.blockchain.info/charts)"

# nombre_metrica -> (chart_key, unidad, polaridad)
# polaridad: cómo interpretar una tendencia "subiendo" en esta métrica
#   "sube_favorable"   -> más actividad/seguridad de red = favorable
#   "sube_desfavorable"-> mayor valoración relativa = desfavorable
#   "neutral"           -> puramente informativo, sin lectura direccional
METRICAS_BLOCKCHAIN_INFO = {
    "direcciones_activas": ("direcciones_activas", "direcciones/día", "sube_favorable"),
    "transacciones": ("transacciones", "tx/día", "sube_favorable"),
    "hash_rate": ("hash_rate", "TH/s", "sube_favorable"),
    "dificultad": ("dificultad", "dificultad", "neutral"),
    "fees_usd": ("fees_usd", "USD/día", "sube_favorable"),
    "suministro": ("suministro", "BTC", "neutral"),
}

METRICAS_NO_DISPONIBLES = [
    "exchange_inflows_outflows",
    "mvrv",
    "sopr",
    "comportamiento_holders",
]

MOTIVO_NO_DISPONIBLE = (
    "NO DISPONIBLE: sin fuente pública y gratuita verificada sin API key "
    "al momento de esta investigación (ver docs/fuentes on-chain)"
)


def _tendencia(valor_reciente: float, valor_previo: float) -> str:
    if valor_previo == 0:
        return "estable"

    variacion_pct = (valor_reciente - valor_previo) / abs(valor_previo) * 100

    if variacion_pct > UMBRAL_TENDENCIA_PCT:
        return "subiendo"
    if variacion_pct < -UMBRAL_TENDENCIA_PCT:
        return "bajando"
    return "estable"


def _partir_en_mitades(valores: list[float]):
    mitad = len(valores) // 2
    if mitad == 0:
        return valores, valores
    return valores[:mitad], valores[mitad:]


def _estado_por_tendencia(tendencia: str, polaridad: str) -> str:
    if tendencia == "sin_datos":
        return "sin_datos"
    if polaridad == "neutral":
        return "neutral"
    if tendencia == "estable":
        return "neutral"
    if polaridad == "sube_favorable":
        return "favorable" if tendencia == "subiendo" else "desfavorable"
    if polaridad == "sube_desfavorable":
        return "desfavorable" if tendencia == "subiendo" else "favorable"
    return "neutral"


def _metrica_no_disponible(nombre: str) -> dict:
    return {
        "metrica": nombre,
        "valor": None,
        "unidad": None,
        "timestamp": None,
        "fuente": MOTIVO_NO_DISPONIBLE,
        "tendencia": "sin_datos",
        "estado": "sin_datos",
    }


def calcular_metrica(nombre: str, provider: BlockchainInfoProvider = None,
                      timespan: str = "30days") -> dict:
    """
    Calcula una métrica on-chain de BTC a partir de su historial en
    Blockchain.com Charts API.
    """
    if nombre not in METRICAS_BLOCKCHAIN_INFO:
        raise ValueError(f"Métrica '{nombre}' no soportada. Usa una de: {list(METRICAS_BLOCKCHAIN_INFO)}")

    chart_key, unidad, polaridad = METRICAS_BLOCKCHAIN_INFO[nombre]
    provider = provider or BlockchainInfoProvider()

    logger.info(f"Calculando métrica on-chain BTC: {nombre}...")
    historial = provider.get_chart(chart_key, timespan=timespan)

    valores = [item["valor"] for item in historial]
    previos, recientes = _partir_en_mitades(valores)
    tendencia = _tendencia(sum(recientes) / len(recientes), sum(previos) / len(previos))

    resultado = {
        "metrica": nombre,
        "valor": historial[-1]["valor"],
        "unidad": unidad,
        "timestamp": historial[-1]["timestamp"],
        "fuente": FUENTE_BLOCKCHAIN_INFO,
        "tendencia": tendencia,
        "estado": _estado_por_tendencia(tendencia, polaridad),
    }
    logger.info(
        f"OK: BTC {nombre} = {resultado['valor']} {unidad} "
        f"tendencia={tendencia} estado={resultado['estado']}"
    )
    return resultado


def calcular_nvt(provider: BlockchainInfoProvider = None, timespan: str = "30days") -> dict:
    """
    NVT (Network Value to Transactions) = Market Cap / Volumen de
    transacciones on-chain (USD). No hay endpoint que lo entregue
    directo y gratis - se calcula con la fórmula pública estándar sobre
    dos series reales de Blockchain.com Charts API (market-cap y
    estimated-transaction-volume-usd).
    """
    provider = provider or BlockchainInfoProvider()

    logger.info("Calculando NVT (Network Value to Transactions) de BTC...")
    market_cap_hist = provider.get_chart("market_cap", timespan=timespan)
    volumen_hist = provider.get_chart("volumen_transacciones_usd", timespan=timespan)

    n = min(len(market_cap_hist), len(volumen_hist))
    nvt_serie = []
    for i in range(n):
        volumen = volumen_hist[i]["valor"]
        if volumen:
            nvt_serie.append(market_cap_hist[i]["valor"] / volumen)

    if not nvt_serie:
        logger.warning("No se pudo calcular NVT: volumen de transacciones en cero o sin datos")
        return _metrica_no_disponible("nvt")

    previos, recientes = _partir_en_mitades(nvt_serie)
    tendencia = _tendencia(sum(recientes) / len(recientes), sum(previos) / len(previos))

    resultado = {
        "metrica": "nvt",
        "valor": nvt_serie[-1],
        "unidad": "ratio",
        "timestamp": market_cap_hist[-1]["timestamp"],
        "fuente": f"{FUENTE_BLOCKCHAIN_INFO} (calculado: market-cap / estimated-transaction-volume-usd)",
        "tendencia": tendencia,
        "estado": _estado_por_tendencia(tendencia, "sube_desfavorable"),
    }
    logger.info(f"OK: BTC NVT = {resultado['valor']:.2f} tendencia={tendencia} estado={resultado['estado']}")
    return resultado


def calcular_onchain_btc(provider: BlockchainInfoProvider = None, timespan: str = "30days") -> list[dict]:
    """
    Devuelve la lista completa de métricas on-chain de BTC: las
    disponibles (calculadas con datos reales) y las NO DISPONIBLES
    (marcadas explícitamente, sin inventar valores).
    """
    provider = provider or BlockchainInfoProvider()
    resultados = []

    for nombre in METRICAS_BLOCKCHAIN_INFO:
        try:
            resultados.append(calcular_metrica(nombre, provider, timespan))
        except BlockchainInfoProviderError as e:
            logger.error(f"No se pudo calcular la métrica BTC {nombre}: {e}")
            resultados.append(_metrica_no_disponible(nombre))

    try:
        resultados.append(calcular_nvt(provider, timespan))
    except BlockchainInfoProviderError as e:
        logger.error(f"No se pudo calcular NVT: {e}")
        resultados.append(_metrica_no_disponible("nvt"))

    for nombre in METRICAS_NO_DISPONIBLES:
        resultados.append(_metrica_no_disponible(nombre))

    return resultados
