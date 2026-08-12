"""
Cálculo de confidence del CryptoScoringEngine.

confidence es distinto de total_score: total_score mide qué tan
favorable/desfavorable luce el activo; confidence mide qué tan
confiable es esa lectura. Se calcula como el promedio de 4 factores
explícitos (0-100 cada uno, peso igual 25% cada uno - una combinación
transparente y documentada, no un ajuste arbitrario):

1. cobertura_datos: % de métricas con datos reales disponibles (no sin_datos)
   entre las 5 categorías.
2. calidad_fuentes: confiabilidad promedio (tabla estática documentada)
   de las fuentes efectivamente usadas.
3. acuerdo_temporalidades: qué tan de acuerdo están 4h/1h/15m en el
   score técnico (poca dispersión = alta confianza). Si el score técnico
   no está disponible, se usa un valor neutral (50).
4. acuerdo_categorias: cuántas de las 5 categorías apuntan en la misma
   dirección (favorable/desfavorable) que la mayoría. Muchas
   contradicciones entre categorías = menos confianza.
"""

RELIABILIDAD_FUENTE = {
    "Blockchain.com Charts API": 90,
    "DefiLlama API": 85,
    "CoinGecko Public API": 70,
    "Binance Klines API": 95,
    "Binance Futures API": 90,
    "Fear & Greed Index": 75,
    "Yahoo Finance": 85,
}

RELIABILIDAD_DEFECTO = 50


def _confiabilidad_de(fuente: str) -> int:
    if not fuente:
        return RELIABILIDAD_DEFECTO
    for prefijo, valor in RELIABILIDAD_FUENTE.items():
        if prefijo in fuente:
            return valor
    return RELIABILIDAD_DEFECTO


def _cobertura_datos(categorias: dict) -> float:
    coberturas = [c["cobertura"] for c in categorias.values() if c.get("cobertura") is not None]
    if not coberturas:
        return 0.0
    return (sum(coberturas) / len(coberturas)) * 100


def _calidad_fuentes(categorias: dict) -> float:
    confiabilidades = []

    for nombre, cat in categorias.items():
        if nombre == "tecnico" and "por_timeframe" in cat:
            for tf in cat["por_timeframe"].values():
                for m in tf.get("metricas", []):
                    if m.get("senal") != "sin_datos":
                        confiabilidades.append(_confiabilidad_de(m.get("fuente")))
        else:
            for m in cat.get("metricas", []):
                if m.get("senal") != "sin_datos":
                    confiabilidades.append(_confiabilidad_de(m.get("fuente")))

    if not confiabilidades:
        return 0.0
    return sum(confiabilidades) / len(confiabilidades)


def _acuerdo_temporalidades(categorias: dict) -> float:
    tecnico = categorias.get("tecnico", {})
    por_timeframe = tecnico.get("por_timeframe")
    if not por_timeframe:
        return 50.0

    fracciones = [tf["puntos"] for tf in por_timeframe.values() if tf.get("disponible") and tf.get("puntos") is not None]
    if len(fracciones) < 2:
        return 50.0

    dispersion = max(fracciones) - min(fracciones)  # 0 (total acuerdo) .. 1 (total desacuerdo)
    return max(0.0, (1 - dispersion) * 100)


def _acuerdo_categorias(categorias: dict, puntos_totales_por_categoria: dict) -> float:
    fracciones = []
    for nombre, cat in categorias.items():
        if cat.get("disponible") and cat.get("puntos") is not None:
            fracciones.append(cat["puntos"] / puntos_totales_por_categoria[nombre])

    if len(fracciones) < 2:
        return 50.0

    alcistas = sum(1 for f in fracciones if f > 0.5)
    bajistas = sum(1 for f in fracciones if f < 0.5)
    neutrales = len(fracciones) - alcistas - bajistas

    mayoria = max(alcistas, bajistas, neutrales)
    return (mayoria / len(fracciones)) * 100


def calcular_confidence(categorias: dict, puntos_totales_por_categoria: dict) -> dict:
    """
    categorias: {"fundamental": resultado, "tecnico": resultado,
                 "derivados": resultado, "sentimiento": resultado, "macro": resultado}
    puntos_totales_por_categoria: {"fundamental": 30, "tecnico": 30, "derivados": 20,
                                    "sentimiento": 10, "macro": 10}
    """
    factores = {
        "cobertura_datos": round(_cobertura_datos(categorias), 2),
        "calidad_fuentes": round(_calidad_fuentes(categorias), 2),
        "acuerdo_temporalidades": round(_acuerdo_temporalidades(categorias), 2),
        "acuerdo_categorias": round(_acuerdo_categorias(categorias, puntos_totales_por_categoria), 2),
    }

    confidence = sum(factores.values()) / len(factores)

    return {
        "confidence": round(confidence, 2),
        "factores": factores,
    }
