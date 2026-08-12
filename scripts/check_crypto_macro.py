"""
Chequeo manual del contexto macro (DXY, US10Y, S&P 500, oro) contra
Yahoo Finance real, vía yfinance. Solo lectura, sin API key.

Uso: python -m scripts.check_crypto_macro
"""

from app.macro.crypto_macro import calcular_contexto_macro


def check_crypto_macro():
    contexto = calcular_contexto_macro()

    for nombre, datos in contexto.items():
        print(
            f"{nombre} ({datos['ticker']}): actual={datos['valor_actual']:.2f} "
            f"variacion={datos['variacion_pct']:.2f}% tendencia={datos['tendencia']}"
        )


if __name__ == "__main__":
    check_crypto_macro()
