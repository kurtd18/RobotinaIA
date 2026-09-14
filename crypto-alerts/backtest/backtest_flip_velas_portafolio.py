"""
Backtest de portafolio (capital + comisiones reales) para la estrategia
de flip de velas diarias encontrada en analisis_patron_flip_velas.py:

  LARGO: vela pasa de roja a verde Y RSI(14) < 30 ese día
  CORTO: vela pasa de verde a roja Y Estocástico(14) > 80 Y Williams%R(14) > -20 ese día

Sobre las 7 monedas seleccionadas, $500,000 COP por entrada,
$10,000,000 COP de capital total, comisiones spot (LARGO)/futuros
(CORTO) igual que en backtest_portafolio.py.

Uso:
    pip install -r requirements.txt
    python backtest_flip_velas_portafolio.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd

from analisis_puntos_quiebre_xrp import EXCHANGE_ID, fetch_ohlcv_full, calcular_indicadores
from analisis_patron_flip_velas import agregar_forma_vela, TIMEFRAME, LOOKBACK_DAYS
from backtest_cron_gaps import SYMBOLS
from backtest_portafolio import CAPITAL_TOTAL_COP, FEE_SPOT, FEE_FUTUROS

TAMANO_POSICION_COP = 500_000
MAX_HOLD_VELAS = 5  # días - misma ventana usada para validar el patrón

CONFIGS_SL_TP = {
    "3% SL / 3% TP": (3.0, 3.0),
    "5% SL / 3% TP": (5.0, 3.0),
    "5% SL / 5% TP": (5.0, 5.0),
    "3% SL / 5% TP": (3.0, 5.0),
}

WARMUP = 200


def generar_senales(df: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    senales = []
    color = df["color"].values

    for i in range(WARMUP + 1, len(df) - 1):
        if color[i - 1] == "roja" and color[i] == "verde" and df["rsi14"].iloc[i] < 30:
            senales.append((df.index[i], "LARGO"))
        elif (color[i - 1] == "verde" and color[i] == "roja"
              and df["stoch_k"].iloc[i] > 80 and df["willr14"].iloc[i] > -20):
            senales.append((df.index[i], "CORTO"))

    return senales


def simular_portafolio(dfs: dict, senales_por_symbol: dict, sl_pct: float, tp_pct: float):
    capital_libre = CAPITAL_TOTAL_COP
    posiciones_abiertas = []
    monedas_con_posicion = set()
    trades = []

    senales_por_ts = {}
    for symbol, lista in senales_por_symbol.items():
        for ts, direccion in lista:
            senales_por_ts.setdefault(ts, []).append((symbol, direccion))

    todos_los_ts = sorted(set().union(*[set(df.index) for df in dfs.values()]))

    for ts in todos_los_ts:
        siguen_abiertas = []
        for pos in posiciones_abiertas:
            df = dfs[pos["symbol"]]
            if ts <= pos["entrada_ts"] or ts not in df.index:
                siguen_abiertas.append(pos)
                continue
            row = df.loc[ts]
            dias_transcurridos = (ts - pos["entrada_ts"]).days

            hit_sl = (row["high"] >= pos["sl_precio"]) if pos["direccion"] == "CORTO" else (row["low"] <= pos["sl_precio"])
            hit_tp = (row["low"] <= pos["tp_precio"]) if pos["direccion"] == "CORTO" else (row["high"] >= pos["tp_precio"])

            resultado, precio_salida = None, None
            if hit_sl:
                resultado, precio_salida = "SL", pos["sl_precio"]
            elif hit_tp:
                resultado, precio_salida = "TP", pos["tp_precio"]
            elif dias_transcurridos >= MAX_HOLD_VELAS:
                resultado, precio_salida = "TIMEOUT", row["close"]

            if resultado is None:
                siguen_abiertas.append(pos)
                continue

            if pos["direccion"] == "LARGO":
                retorno = (precio_salida - pos["entrada_precio"]) / pos["entrada_precio"]
            else:
                retorno = (pos["entrada_precio"] - precio_salida) / pos["entrada_precio"]

            valor_salida = pos["tamano_cop"] * (1 + retorno)
            fee_salida = valor_salida * pos["fee_rate"]
            capital_libre += valor_salida - fee_salida
            pnl_neto_cop = (valor_salida - fee_salida) - (pos["tamano_cop"] + pos["fee_entrada_cop"])

            trades.append({
                "symbol": pos["symbol"], "direccion": pos["direccion"], "resultado": resultado,
                "entrada_ts": pos["entrada_ts"], "salida_ts": ts, "pnl_neto_cop": round(pnl_neto_cop),
            })
            monedas_con_posicion.discard(pos["symbol"])
        posiciones_abiertas = siguen_abiertas

        for symbol, direccion in senales_por_ts.get(ts, []):
            if symbol in monedas_con_posicion or capital_libre < TAMANO_POSICION_COP:
                continue

            fee_rate = FEE_FUTUROS if direccion == "CORTO" else FEE_SPOT
            entrada_precio = dfs[symbol].loc[ts, "close"]
            fee_entrada_cop = TAMANO_POSICION_COP * fee_rate
            capital_libre -= (TAMANO_POSICION_COP + fee_entrada_cop)

            if direccion == "CORTO":
                sl_precio, tp_precio = entrada_precio * (1 + sl_pct / 100), entrada_precio * (1 - tp_pct / 100)
            else:
                sl_precio, tp_precio = entrada_precio * (1 - sl_pct / 100), entrada_precio * (1 + tp_pct / 100)

            posiciones_abiertas.append({
                "symbol": symbol, "direccion": direccion, "entrada_ts": ts, "entrada_precio": entrada_precio,
                "sl_precio": sl_precio, "tp_precio": tp_precio, "fee_rate": fee_rate,
                "fee_entrada_cop": fee_entrada_cop, "tamano_cop": TAMANO_POSICION_COP,
            })
            monedas_con_posicion.add(symbol)

    capital_abierto = 0
    for pos in posiciones_abiertas:
        ultimo = dfs[pos["symbol"]]["close"].iloc[-1]
        retorno = ((ultimo - pos["entrada_precio"]) if pos["direccion"] == "LARGO"
                   else (pos["entrada_precio"] - ultimo)) / pos["entrada_precio"]
        capital_abierto += pos["tamano_cop"] * (1 + retorno)

    return pd.DataFrame(trades), capital_libre, capital_abierto


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    dfs, senales_por_symbol = {}, {}
    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = calcular_indicadores(df)
        df = agregar_forma_vela(df)
        dfs[symbol] = df
        senales_por_symbol[symbol] = generar_senales(df)

    filas = []
    for nombre, (sl, tp) in CONFIGS_SL_TP.items():
        trades, cap_libre, cap_abierto = simular_portafolio(dfs, senales_por_symbol, sl, tp)
        capital_final = cap_libre + cap_abierto
        total = len(trades)
        wins = (trades["resultado"] == "TP").sum() if total else 0
        filas.append({
            "config": nombre, "trades": total,
            "win_rate_%": round(wins / total * 100, 1) if total else 0.0,
            "ganancia_neta_cop": round(capital_final - CAPITAL_TOTAL_COP),
            "ganancia_neta_%": round((capital_final - CAPITAL_TOTAL_COP) / CAPITAL_TOTAL_COP * 100, 2),
        })
        if nombre == "3% SL / 3% TP":
            trades.to_csv("resultados_flip_velas_backtest.csv", index=False)

    print("\n" + "=" * 70)
    print(f"BACKTEST ESTRATEGIA FLIP DE VELAS (7 monedas, ${TAMANO_POSICION_COP:,.0f} COP/entrada)")
    print("=" * 70)
    print(pd.DataFrame(filas).to_string(index=False))


if __name__ == "__main__":
    main()
