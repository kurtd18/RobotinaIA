"""
Chequeo manual de derivados cripto (funding rate, open interest) contra
la API pública real de Binance Futures. Solo lectura, sin API key.

Uso: python -m scripts.check_crypto_derivatives
"""

from app.derivatives.crypto_derivatives import calcular_derivados

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]


def check_crypto_derivatives():
    for symbol in SIMBOLOS:
        print(f"\n=== {symbol} ===")
        derivados = calcular_derivados(symbol)

        fr = derivados["funding_rate"]
        print(
            f"Funding rate: actual={fr['funding_rate_actual']:.6f} "
            f"promedio={fr['funding_rate_promedio']:.6f} "
            f"tendencia={fr['funding_rate_tendencia']} "
            f"({len(fr['historial'])} registros)"
        )

        oi = derivados["open_interest"]
        print(
            f"Open interest: actual={oi['open_interest_actual']} "
            f"promedio={oi['open_interest_promedio']:.2f} "
            f"variacion={oi['open_interest_variacion_pct']:.2f}% "
            f"tendencia={oi['open_interest_tendencia']} "
            f"({len(oi['historial'])} registros)"
        )


if __name__ == "__main__":
    check_crypto_derivatives()
