"""
Chequeo manual de métricas on-chain/fundamentales de ETH contra las APIs
públicas reales de DefiLlama y CoinGecko. Solo lectura, sin API key.

Uso: python -m scripts.check_eth_onchain
"""

from app.onchain.eth_onchain import calcular_onchain_eth


def check_eth_onchain():
    resultados = calcular_onchain_eth()

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
    check_eth_onchain()
