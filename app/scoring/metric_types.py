"""
Motor genérico de puntaje por categoría del CryptoScoringEngine (Fase 7).

Cada categoría (fundamental, técnico, derivados, sentimiento, macro) se
compone de varias métricas. Cada métrica llega ya con una señal
("favorable"/"neutral"/"desfavorable"/"sin_datos") determinada por una
regla explícita de su propio dominio (ver fundamental_score.py,
technical_score.py, etc.) - este módulo NO decide señales, solo combina
señales ya decididas en un puntaje de categoría.

Regla de combinación (no es un promedio de valores crudos, es un
promedio de señales ya evaluadas):
- favorable   -> 1.0
- neutral     -> 0.5
- desfavorable -> 0.0
- sin_datos   -> excluida del cálculo (no penaliza, no favorece)

puntos_categoria = puntos_totales * promedio(valor_señal de las métricas disponibles)

Si NINGUNA métrica de la categoría tiene datos, la categoría no se
califica en 0 (sería penalizar por falta de datos) ni se asume
automáticamente positiva - queda marcada como no disponible y quien la
use decide el tratamiento (ver crypto_scoring_engine.py).
"""

VALOR_POR_SENAL = {
    "favorable": 1.0,
    "neutral": 0.5,
    "desfavorable": 0.0,
}


def puntaje_categoria(metricas: list[dict], puntos_totales: float) -> dict:
    """
    metricas: lista de dicts, cada uno con al menos {"senal": ...}
              (además de metrica/valor/unidad/timestamp/fuente, que se
              conservan tal cual en la salida).

    Devuelve:
    {
        "puntos": float | None,   # puntos obtenidos sobre puntos_totales, None si no hay datos
        "disponible": bool,
        "cobertura": float,       # fracción de métricas con datos (0-1)
        "metricas": [...],        # las mismas métricas, con "peso" y "puntos" agregados
    }
    """
    disponibles = [m for m in metricas if m.get("senal") in VALOR_POR_SENAL]
    total = len(metricas)
    n_disponibles = len(disponibles)

    if n_disponibles == 0:
        for m in metricas:
            m["peso"] = 0.0
            m["puntos"] = 0.0
        return {
            "puntos": None,
            "disponible": False,
            "cobertura": 0.0,
            "metricas": metricas,
        }

    peso_individual = 1.0 / n_disponibles
    promedio = sum(VALOR_POR_SENAL[m["senal"]] for m in disponibles) / n_disponibles

    for m in metricas:
        if m in disponibles:
            m["peso"] = peso_individual
            m["puntos"] = round(VALOR_POR_SENAL[m["senal"]] * puntos_totales * peso_individual, 4)
        else:
            m["peso"] = 0.0
            m["puntos"] = 0.0

    return {
        "puntos": round(promedio * puntos_totales, 4),
        "disponible": True,
        "cobertura": n_disponibles / total if total else 0.0,
        "metricas": metricas,
    }
