"""
Análisis manual del CryptoScoringEngine contra APIs públicas reales
(Binance, Blockchain.com, DefiLlama, CoinGecko, Fear&Greed, yfinance).
Solo lectura, sin API key, sin conexión a cuentas reales, sin ejecutar
ninguna operación. Persiste el resultado en robotinaia.db
(tabla crypto_scores) para poder detectar cambios de señal en la
siguiente corrida.

Uso: python -m scripts.check_crypto_scoring
"""

from app.scoring.crypto_scoring_engine import SIMBOLOS_SOPORTADOS, CryptoScoringEngine

SIMBOLOS = list(SIMBOLOS_SOPORTADOS)


def _mostrar_categoria(nombre, cat, maximo):
    print(f"\n--- {nombre.upper()} ({cat['puntos'] if cat['puntos'] is not None else 'N/D'}/{maximo}) ---")
    if nombre == "tecnico" and "por_timeframe" in cat:
        for tf, datos in cat["por_timeframe"].items():
            print(f"  [{tf}] disponible={datos['disponible']} fracción={datos.get('puntos')}")
            for m in datos.get("metricas", []):
                print(f"    - {m['metrica']}: valor={m['valor']} señal={m['senal']} peso={m.get('peso')} puntos={m.get('puntos')}")
        return

    for m in cat.get("metricas", []):
        print(f"  - {m['metrica']}: valor={m['valor']} señal={m['senal']} fuente={m['fuente']} puntos={m.get('puntos')}")


def check_crypto_scoring():
    engine = CryptoScoringEngine()

    for symbol in SIMBOLOS:
        print(f"\n{'=' * 70}\nANÁLISIS {symbol}\n{'=' * 70}")

        resultado = engine.analizar(symbol)

        print(f"\nSCORE TOTAL: {resultado['total_score']}/100")
        print(f"CONFIDENCE: {resultado['confidence']}%  (factores: {resultado['confidence_factores']})")
        print(f"SEÑAL CANDIDATA: {resultado['signal_candidata']}")
        print(f"SEÑAL FINAL: {resultado['signal']}")
        if resultado["risk_reward"]:
            print(f"RIESGO/BENEFICIO: {resultado['risk_reward']}")
        if resultado["cambio_senal"]:
            print(f"CAMBIO DE SEÑAL: {resultado['cambio_senal']['de']} -> {resultado['cambio_senal']['a']}")
        else:
            print("CAMBIO DE SEÑAL: sin cambio respecto al último análisis (o es el primero)")

        print("\nRAZONES:")
        for r in resultado["razones"]:
            print(f"  - {r}")

        maximos = {"fundamental": 30, "tecnico": 30, "derivados": 20, "sentimiento": 10, "macro": 10}
        for nombre, cat in resultado["detalle_categorias"].items():
            _mostrar_categoria(nombre, cat, maximos[nombre])

        print(f"\nMÉTRICAS SIN DATOS ({len(resultado['metricas_sin_datos'])}):")
        for m in resultado["metricas_sin_datos"]:
            print(f"  - {m}")


if __name__ == "__main__":
    check_crypto_scoring()
