"""
Chequeo manual de métricas on-chain de BTC contra la API pública real de
Blockchain.com. Solo lectura, sin API key.

Uso: python -m scripts.check_btc_onchain
"""

from app.onchain.btc_onchain import calcular_onchain_btc


def check_btc_onchain():
    resultados = calcular_onchain_btc()

    for r in resultados:
        if r["valor"] is None:
            print(f"{r['metrica']}: {r['fuente']}")
        else:
            print(
                f"{r['metrica']}: {r['valor']:.4f} {r['unidad']} "
                f"@ {r['timestamp']} | tendencia={r['tendencia']} estado={r['estado']} "
                f"| fuente={r['fuente']}"
            )


if __name__ == "__main__":
    check_btc_onchain()
