"""
Mide la precisión de los gatillos de la estrategia de flip de velas
(la que está en producción) MONEDA POR MONEDA, sobre un universo
candidato de 20 monedas líquidas de Binance, para decidir cuáles
entran al portafolio ampliado.

Gatillos evaluados (los mismos de crypto-alerts/analyze_and_notify.py):
  - LARGO: flip roja->verde + RSI(14) < 30 el día del flip
           éxito = >=5% a favor en <=3 días (criterio estricto, el que
           mostró ventaja real sobre XRP/ADA/DOGE/LINK/AVAX/DOT/LTC)
  - CORTO: flip verde->roja + Estocástico(14)>80 Y Williams%R(14)>-20
           éxito = >=3% a favor en <=5 días

Uso:
    pip install -r requirements.txt
    python analisis_precision_flip_por_moneda.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd

from analisis_puntos_quiebre_xrp import EXCHANGE_ID, fetch_ohlcv_full, calcular_indicadores
from analisis_patron_flip_velas import agregar_forma_vela, detectar_flips, marcar_exito, TIMEFRAME, LOOKBACK_DAYS

WARMUP = 200

# Universo candidato: 20 monedas líquidas con par USDT en Binance spot,
# listadas desde antes de 2024-09 (para tener el historial completo de
# 730 días). Incluye a las 7 ya validadas (deben volver a aparecer acá)
# más 13 candidatas nuevas.
CANDIDATOS_20 = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "SOL/USDT",
    "ADA/USDT", "DOGE/USDT", "TRX/USDT", "LINK/USDT", "AVAX/USDT",
    "DOT/USDT", "LTC/USDT", "BCH/USDT", "ATOM/USDT", "UNI/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "ETC/USDT",
]

# Umbrales mínimos para incluir una moneda en el universo final.
PRECISION_MINIMA_LARGO = 50.0   # base estricta era 40.0% - exigir >=50%
PRECISION_MINIMA_CORTO = 75.0   # base era 70.9% - exigir >=75%
ACTIVACIONES_MINIMAS = 3        # al menos 3 señales en 730 días para no decidir con 1 dato suelto


def gatillo_largo(df, i):
    return df["rsi14"].iloc[i] < 30


def gatillo_corto(df, i):
    return df["stoch_k"].iloc[i] > 80 and df["willr14"].iloc[i] > -20


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    filas = []
    for symbol in CANDIDATOS_20:
        print(f"Procesando {symbol} ...")
        try:
            df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        except Exception as e:
            print(f"  Omitida ({e})")
            continue

        if len(df) < WARMUP + 10:
            print(f"  Omitida: solo {len(df)} velas (historial insuficiente)")
            continue

        df = calcular_indicadores(df)
        df = agregar_forma_vela(df)

        flips_largo, flips_corto = detectar_flips(df, WARMUP)

        activados_largo = [i for i in flips_largo if gatillo_largo(df, i)]
        activados_corto = [i for i in flips_corto if gatillo_corto(df, i)]

        exitos_largo = marcar_exito(df, activados_largo, "LARGO", ganancia_minima_pct=5.0, ventana_velas=3)
        exitos_corto = marcar_exito(df, activados_corto, "CORTO", ganancia_minima_pct=3.0, ventana_velas=5)

        precision_largo = exitos_largo.mean() * 100 if len(activados_largo) else None
        precision_corto = exitos_corto.mean() * 100 if len(activados_corto) else None

        filas.append({
            "symbol": symbol,
            "velas_disponibles": len(df),
            "activaciones_largo": len(activados_largo),
            "precisión_largo_%": round(precision_largo, 1) if precision_largo is not None else None,
            "activaciones_corto": len(activados_corto),
            "precisión_corto_%": round(precision_corto, 1) if precision_corto is not None else None,
        })

    df_resultado = pd.DataFrame(filas)
    print("\n" + "=" * 100)
    print("PRECISIÓN DE LOS GATILLOS DE PRODUCCIÓN, POR MONEDA (20 candidatas)")
    print("=" * 100)
    print(df_resultado.to_string(index=False))
    df_resultado.to_csv("resultados_precision_flip_20_monedas.csv", index=False)

    cumple_largo = (
        (df_resultado["precisión_largo_%"].fillna(0) >= PRECISION_MINIMA_LARGO) &
        (df_resultado["activaciones_largo"].fillna(0) >= ACTIVACIONES_MINIMAS)
    )
    cumple_corto = (
        (df_resultado["precisión_corto_%"].fillna(0) >= PRECISION_MINIMA_CORTO) &
        (df_resultado["activaciones_corto"].fillna(0) >= ACTIVACIONES_MINIMAS)
    )

    seleccionadas = df_resultado[cumple_largo | cumple_corto]["symbol"].tolist()
    print("\n" + "-" * 100)
    print(f"UNIVERSO SELECCIONADO (precisión LARGO >= {PRECISION_MINIMA_LARGO}% O CORTO >= {PRECISION_MINIMA_CORTO}%, "
          f">= {ACTIVACIONES_MINIMAS} activaciones)")
    print("-" * 100)
    print(seleccionadas)


if __name__ == "__main__":
    main()
