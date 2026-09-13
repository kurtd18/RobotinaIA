"""
Sondeo de la mejor combinación de Stop-Loss / Take-Profit entre 1% y 5%
(en pasos de 0.5%), sobre el universo de 7 monedas seleccionadas por
precisión (XRP, ADA, DOGE, LINK, AVAX, DOT, LTC), con entradas fijas de
$500,000 COP y capital total de $10,000,000 COP.

Las señales de entrada (gatillo triple para LARGO, RSI solo para CORTO)
no dependen de SL/TP, así que se calculan una sola vez y se reutilizan
en las 81 combinaciones (9x9) - solo cambia la simulación de salida.

Uso:
    pip install -r requirements.txt
    python backtest_sondeo_sltp.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd

from backtest_cron_gaps import (
    EXCHANGE_ID, SYMBOLS, TIMEFRAME, LOOKBACK_DAYS, add_indicators, fetch_ohlcv_full,
)
from backtest_portafolio import agregar_mfi_bollinger, generar_senales, simular_portafolio, CAPITAL_TOTAL_COP

TAMANO_POSICION_COP = 500_000
VALORES_PCT = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    dfs = {}
    senales_por_symbol = {}
    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = add_indicators(df)
        df = agregar_mfi_bollinger(df)
        dfs[symbol] = df
        senales_por_symbol[symbol] = generar_senales(df)

    print(f"\nSondeo SL/TP de {VALORES_PCT[0]}% a {VALORES_PCT[-1]}% "
          f"({len(VALORES_PCT)}x{len(VALORES_PCT)} = {len(VALORES_PCT)**2} combinaciones)")
    print(f"Entrada ${TAMANO_POSICION_COP:,.0f} COP | Capital ${CAPITAL_TOTAL_COP:,.0f} COP\n")

    filas = []
    for sl_pct in VALORES_PCT:
        for tp_pct in VALORES_PCT:
            (trades, capital_libre, capital_abierto, _perd_cap,
             _perd_pos) = simular_portafolio(dfs, senales_por_symbol, sl_pct, tp_pct, TAMANO_POSICION_COP)

            capital_final = capital_libre + capital_abierto
            ganancia_neta = capital_final - CAPITAL_TOTAL_COP
            total = len(trades)
            wins = (trades["resultado"] == "TP").sum() if total else 0
            breakeven = sl_pct / (sl_pct + tp_pct) * 100

            filas.append({
                "sl_%": sl_pct, "tp_%": tp_pct,
                "ratio_riesgo_beneficio": round(sl_pct / tp_pct, 2),
                "win_rate_equilibrio_%": round(breakeven, 1),
                "trades": total,
                "win_rate_%": round(wins / total * 100, 1) if total else 0.0,
                "margen_sobre_equilibrio_pp": round((wins / total * 100 - breakeven), 1) if total else None,
                "ganancia_neta_cop": round(ganancia_neta),
                "ganancia_neta_%": round(ganancia_neta / CAPITAL_TOTAL_COP * 100, 2),
            })

    df_resultado = pd.DataFrame(filas)
    df_resultado_ordenado = df_resultado.sort_values("ganancia_neta_cop", ascending=False)

    print("=" * 110)
    print("TOP 15 COMBINACIONES SL/TP POR GANANCIA NETA")
    print("=" * 110)
    print(df_resultado_ordenado.head(15).to_string(index=False))

    print("\n" + "=" * 110)
    print("PEOR 5 COMBINACIONES (referencia)")
    print("=" * 110)
    print(df_resultado_ordenado.tail(5).to_string(index=False))

    # Tabla tipo "mapa de calor" en texto: ganancia_% con SL en filas, TP en columnas
    pivote = df_resultado.pivot(index="sl_%", columns="tp_%", values="ganancia_neta_%")
    print("\n" + "=" * 110)
    print("MAPA DE GANANCIA NETA % (filas = SL, columnas = TP)")
    print("=" * 110)
    print(pivote.to_string())

    df_resultado.to_csv("resultados_sondeo_sltp.csv", index=False)
    print("\nGuardado: resultados_sondeo_sltp.csv")


if __name__ == "__main__":
    main()
