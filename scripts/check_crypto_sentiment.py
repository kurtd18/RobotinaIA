"""
Chequeo manual del Fear & Greed Index contra la API pública real de
alternative.me. Solo lectura, sin API key.

Uso: python -m scripts.check_crypto_sentiment
"""

from app.sentiment.crypto_sentiment import calcular_sentimiento


def check_crypto_sentiment():
    resultado = calcular_sentimiento()

    print(
        f"Fear & Greed Index actual: {resultado['valor_actual']} "
        f"({resultado['clasificacion_actual']})"
    )
    print(f"Promedio ({len(resultado['historial'])} días): {resultado['valor_promedio']:.1f}")
    print(f"Tendencia: {resultado['tendencia']}")


if __name__ == "__main__":
    check_crypto_sentiment()
