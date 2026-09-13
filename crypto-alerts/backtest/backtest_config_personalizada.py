"""
Corrida puntual del backtest de portafolio con parámetros específicos
pedidos por el usuario: universo de 7 monedas seleccionadas por
precisión (XRP, ADA, DOGE, LINK, AVAX, DOT, LTC), take-profit 1.5%,
stop-loss 3%, $500,000 COP por entrada, capital total $10,000,000 COP.

Uso:
    pip install -r requirements.txt
    python backtest_config_personalizada.py
"""

from datetime import datetime, timedelta, timezone

import ccxt

from backtest_cron_gaps import (
    EXCHANGE_ID, SYMBOLS, TIMEFRAME, LOOKBACK_DAYS, add_indicators, fetch_ohlcv_full,
)
from backtest_portafolio import (
    CAPITAL_TOTAL_COP, agregar_mfi_bollinger, generar_senales, simular_portafolio,
)

SL_PCT = 3.0
TP_PCT = 1.5
TAMANO_POSICION_COP = 500_000


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

    print(f"\nUniverso: {SYMBOLS}")
    print(f"SL {SL_PCT}% / TP {TP_PCT}% | Entrada ${TAMANO_POSICION_COP:,.0f} COP | "
          f"Capital ${CAPITAL_TOTAL_COP:,.0f} COP")

    (trades, capital_libre, capital_abierto, perdidas_capital,
     perdidas_pos_abierta) = simular_portafolio(dfs, senales_por_symbol, SL_PCT, TP_PCT, TAMANO_POSICION_COP)

    capital_final = capital_libre + capital_abierto
    ganancia_neta = capital_final - CAPITAL_TOTAL_COP
    total = len(trades)

    if total:
        wins = (trades["resultado"] == "TP").sum()
        ganadores = trades[trades["resultado"] == "TP"]
        horas_prom_tp = ganadores["horas_hasta_salida"].mean() if not ganadores.empty else None

        print("\n--- Trades por moneda ---")
        print(trades.groupby("symbol")["pnl_neto_cop"].agg(trades="count", pnl_total_cop="sum").to_string())

        print(f"\nTrades ejecutados: {total}")
        print(f"Win rate: {wins / total * 100:.1f}%")
        if horas_prom_tp is not None:
            print(f"Tiempo promedio hasta TP: {horas_prom_tp:.1f}h (~{horas_prom_tp / 24:.1f} días)")
    else:
        print("Sin trades ejecutados.")

    print(f"\nSeñales descartadas por falta de capital libre: {perdidas_capital}")
    print(f"Señales descartadas por ya tener posición abierta en esa moneda: {perdidas_pos_abierta}")
    print(f"\nCapital inicial:        ${CAPITAL_TOTAL_COP:,.0f} COP")
    print(f"Capital libre al final: ${capital_libre:,.0f} COP")
    print(f"Valor en posiciones abiertas al final (mark-to-market): ${capital_abierto:,.0f} COP")
    print(f"Capital final total:   ${capital_final:,.0f} COP")
    print(f"Ganancia/pérdida neta (ya con comisiones): ${ganancia_neta:,.0f} COP "
          f"({ganancia_neta / CAPITAL_TOTAL_COP * 100:.2f}%)")

    trades.to_csv("resultados_config_personalizada.csv", index=False)


if __name__ == "__main__":
    main()
