"""
Score fundamental/on-chain (30 puntos) del CryptoScoringEngine.

Reutiliza directamente app/onchain/btc_onchain.py y eth_onchain.py (Fase
6) - la señal de cada métrica ya viene determinada por la regla
explícita de tendencia de esa fase (estado: favorable/neutral/
desfavorable/sin_datos). Este módulo solo selecciona el subconjunto de
métricas relevante para el score y las combina con metric_types.

BTC: NVT, hash rate, direcciones activas, transacciones, fees, suministro, dificultad.
ETH: TVL Ethereum, TVL L2 (agregado por mayoría), evolución individual de
     Arbitrum/Optimism/Base, suministro.

Los demás activos soportados por CryptoScoringEngine (SOL, BNB, XRP, ADA,
DOGE, AVAX, LINK, TON) no tienen todavía un proveedor on-chain propio
(Fase 6 solo cubre BTC y ETH) - para esos, el score fundamental queda
sin datos (disponible=False), y CryptoScoringEngine lo trata como
categoría neutral (no penaliza ni favorece por no tener fuente on-chain
propia). No se inventa ninguna métrica para esos activos.
"""

from app.onchain.btc_onchain import calcular_onchain_btc
from app.onchain.eth_onchain import calcular_onchain_eth
from app.scoring.metric_types import puntaje_categoria

PUNTOS_TOTALES = 30

METRICAS_BTC = ["nvt", "hash_rate", "direcciones_activas", "transacciones", "fees_usd", "suministro", "dificultad"]
METRICAS_ETH = ["tvl_defi_ethereum", "tvl_l2_arbitrum", "tvl_l2_optimism", "tvl_l2_base", "suministro"]


def _a_metrica_scoring(item: dict) -> dict:
    """Traduce {metrica, valor, unidad, timestamp, fuente, tendencia, estado}
    (formato de Fase 6) al formato genérico {..., senal} de metric_types."""
    return {
        "metrica": item["metrica"],
        "valor": item["valor"],
        "unidad": item["unidad"],
        "timestamp": item["timestamp"],
        "fuente": item["fuente"],
        "senal": item["estado"],  # favorable/neutral/desfavorable/sin_datos
    }


def _tvl_l2_agregado(metricas_eth: list[dict]) -> dict:
    """Combina la señal de los 3 L2 (Arbitrum/Optimism/Base) por mayoría,
    sin volver a llamar a ninguna API - es una lectura derivada de datos
    ya obtenidos, no una nueva métrica inventada."""
    l2 = [m for m in metricas_eth if m["metrica"] in ("tvl_l2_arbitrum", "tvl_l2_optimism", "tvl_l2_base")]
    disponibles = [m for m in l2 if m["estado"] != "sin_datos"]

    if not disponibles:
        senal = "sin_datos"
    else:
        conteo = {"favorable": 0, "neutral": 0, "desfavorable": 0}
        for m in disponibles:
            conteo[m["estado"]] += 1
        senal = max(conteo, key=conteo.get)

    return {
        "metrica": "tvl_l2_total",
        "valor": None,
        "unidad": None,
        "timestamp": None,
        "fuente": f"Agregado por mayoría de {len(disponibles)}/3 chains L2 (Fase 6, DefiLlama)",
        "senal": senal,
    }


def calcular_score_fundamental_btc(provider=None) -> dict:
    todas = calcular_onchain_btc(provider)
    por_nombre = {m["metrica"]: m for m in todas}

    seleccionadas = [
        _a_metrica_scoring(por_nombre[nombre]) if nombre in por_nombre
        else {"metrica": nombre, "valor": None, "unidad": None, "timestamp": None,
              "fuente": "no calculada", "senal": "sin_datos"}
        for nombre in METRICAS_BTC
    ]

    return puntaje_categoria(seleccionadas, PUNTOS_TOTALES)


def calcular_score_fundamental_eth(defillama_provider=None, coingecko_provider=None) -> dict:
    todas = calcular_onchain_eth(defillama_provider, coingecko_provider)
    por_nombre = {m["metrica"]: m for m in todas}

    seleccionadas = [
        _a_metrica_scoring(por_nombre[nombre]) if nombre in por_nombre
        else {"metrica": nombre, "valor": None, "unidad": None, "timestamp": None,
              "fuente": "no calculada", "senal": "sin_datos"}
        for nombre in METRICAS_ETH
    ]
    seleccionadas.append(_tvl_l2_agregado(todas))

    return puntaje_categoria(seleccionadas, PUNTOS_TOTALES)


def calcular_score_fundamental(symbol: str, btc_provider=None, defillama_provider=None,
                                coingecko_provider=None) -> dict:
    if symbol == "BTCUSDT":
        return calcular_score_fundamental_btc(btc_provider)
    if symbol == "ETHUSDT":
        return calcular_score_fundamental_eth(defillama_provider, coingecko_provider)

    # sin proveedor on-chain propio para este activo (ver docstring del
    # módulo) - se devuelve "sin datos" explícito, nunca se inventa una
    # métrica ni se asume un valor
    return puntaje_categoria([], PUNTOS_TOTALES)
