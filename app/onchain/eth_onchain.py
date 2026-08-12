"""
Métricas fundamentales/on-chain de Ethereum.

Fase 6 de RobotinaIA Crypto: expone cada métrica como
{metrica, valor, unidad, timestamp, fuente, tendencia, estado}.
NO calcula un score 0-100 ni genera señales LONG/SHORT - eso es una
fase posterior.

Fuentes: ver docstrings de cada provider en app/onchain/providers/.
Las métricas sin fuente pública gratuita verificada (direcciones activas,
transacciones, fees, ETH burned, emisión neta, staking - todas requieren
Etherscan con API key o beaconcha.in, cuyo tier gratuito fue
descontinuado) se marcan explícitamente como NO_DISPONIBLE, sin inventar
valores. La actividad de Layer 2 solo se aproxima parcialmente vía TVL
(DefiLlama), no hay fuente pública gratuita de conteo de transacciones L2.
"""

from loguru import logger

from app.onchain.providers.coingecko_provider import CoinGeckoProvider, CoinGeckoProviderError
from app.onchain.providers.defillama_provider import DefiLlamaProvider, DefiLlamaProviderError

UMBRAL_TENDENCIA_PCT = 1.0

FUENTE_DEFILLAMA = "DefiLlama API (api.llama.fi/v2/historicalChainTvl)"
FUENTE_COINGECKO = "CoinGecko Public API (api.coingecko.com/api/v3/coins)"

CHAINS_L2 = ["Arbitrum", "Optimism", "Base"]

METRICAS_NO_DISPONIBLES = [
    "direcciones_activas",
    "transacciones",
    "fees",
    "eth_burned",
    "emision_neta",
    "staking",
]

MOTIVO_NO_DISPONIBLE = (
    "NO DISPONIBLE: requiere Etherscan (API key obligatoria) o "
    "beaconcha.in (tier gratuito descontinuado) - sin fuente pública "
    "gratuita verificada al momento de esta investigación"
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


def calcular_tvl(nombre_metrica: str, chain: str, provider: DefiLlamaProvider = None) -> dict:
    """
    TVL histórico de una chain vía DefiLlama. Más TVL/tendencia al alza
    se interpreta como más actividad DeFi (favorable); a la baja, como
    salida de capital (desfavorable).
    """
    provider = provider or DefiLlamaProvider()

    logger.info(f"Calculando TVL on-chain ETH: {nombre_metrica} ({chain})...")
    historial = provider.get_chain_tvl_history(chain)

    valores = [item["tvl_usd"] for item in historial]
    previos, recientes = _partir_en_mitades(valores)
    tendencia = _tendencia(sum(recientes) / len(recientes), sum(previos) / len(previos))
    estado = "neutral" if tendencia == "estable" else ("favorable" if tendencia == "subiendo" else "desfavorable")

    resultado = {
        "metrica": nombre_metrica,
        "valor": historial[-1]["tvl_usd"],
        "unidad": "USD",
        "timestamp": historial[-1]["timestamp"],
        "fuente": FUENTE_DEFILLAMA,
        "tendencia": tendencia,
        "estado": estado,
    }
    logger.info(
        f"OK: ETH {nombre_metrica} = {resultado['valor']:.0f} USD "
        f"tendencia={tendencia} estado={estado}"
    )
    return resultado


def calcular_suministro(provider: CoinGeckoProvider = None) -> dict:
    """
    Suministro circulante/total de ETH vía CoinGecko. Es una foto
    (snapshot) actual, no un historial - no se calcula tendencia (se
    marca "sin_datos" en vez de inventar una dirección) porque este
    endpoint no expone series históricas de suministro.
    """
    provider = provider or CoinGeckoProvider()

    logger.info("Calculando suministro ETH (snapshot)...")
    datos = provider.get_supply("ethereum")

    resultado = {
        "metrica": "suministro",
        "valor": datos["circulating_supply"],
        "unidad": "ETH",
        "timestamp": None,  # snapshot en tiempo real, la API no expone su propio timestamp
        "fuente": FUENTE_COINGECKO,
        "tendencia": "sin_datos",
        "estado": "neutral",
    }
    logger.info(f"OK: ETH suministro circulante = {resultado['valor']}")
    return resultado


def calcular_onchain_eth(defillama_provider: DefiLlamaProvider = None,
                          coingecko_provider: CoinGeckoProvider = None) -> list[dict]:
    """
    Devuelve la lista completa de métricas on-chain/fundamentales de
    ETH: las disponibles (calculadas con datos reales) y las NO
    DISPONIBLES (marcadas explícitamente, sin inventar valores).
    """
    defillama_provider = defillama_provider or DefiLlamaProvider()
    coingecko_provider = coingecko_provider or CoinGeckoProvider()
    resultados = []

    try:
        resultados.append(calcular_tvl("tvl_defi_ethereum", "Ethereum", defillama_provider))
    except DefiLlamaProviderError as e:
        logger.error(f"No se pudo calcular TVL DeFi de Ethereum: {e}")
        resultados.append(_metrica_no_disponible("tvl_defi_ethereum"))

    for chain in CHAINS_L2:
        nombre = f"tvl_l2_{chain.lower()}"
        try:
            resultados.append(calcular_tvl(nombre, chain, defillama_provider))
        except DefiLlamaProviderError as e:
            logger.error(f"No se pudo calcular TVL L2 de {chain}: {e}")
            resultados.append(_metrica_no_disponible(nombre))

    try:
        resultados.append(calcular_suministro(coingecko_provider))
    except CoinGeckoProviderError as e:
        logger.error(f"No se pudo calcular suministro ETH: {e}")
        resultados.append(_metrica_no_disponible("suministro"))

    for nombre in METRICAS_NO_DISPONIBLES:
        resultados.append(_metrica_no_disponible(nombre))

    return resultados
