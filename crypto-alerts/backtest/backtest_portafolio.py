"""
Backtest de portafolio con capital limitado y comisiones reales - a
diferencia de backtest_cron_gaps.py (que mide PnL% "por trade" como si
cada señal tuviera capital ilimitado propio), acá se simula un solo
capital compartido entre las 4 monedas:

  - Capital total: $5,000,000 COP
  - Tamaño fijo por entrada: $500,000 COP (10 cupos posibles en total,
    repartidos entre las monedas que den señal en cada momento)
  - Si se activa una señal pero no hay cupo de capital libre, esa señal
    se descarta (no se apalanca ni se espera - se pierde la entrada)
  - Comisión de compra + venta: 0.10% en spot (usada para LARGO) y
    0.05% en futuros (usada para CORTO, porque abrir corto normalmente
    requiere futuros/margen)

Usa el mismo cron y ventana de cruce "DESPUES" (producción actual) y la
misma regla de entrada de analyze_and_notify.py / backtest_cron_gaps.py.

Uso:
    pip install -r requirements.txt
    python backtest_portafolio.py
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

from backtest_cron_gaps import (
    EXCHANGE_ID, SYMBOLS, TIMEFRAME, LOOKBACK_DAYS, WARMUP, MAX_HOLD_HOURS,
    CRON_DESPUES_HORAS_UTC, CRON_DESPUES_VENTANA, RSI_OVERSOLD, RSI_OVERBOUGHT,
    fetch_ohlcv_full, add_indicators,
)
import ccxt

# Si True, usa el gatillo triple RSI+MFI+Bollinger%B (validado en
# analisis_combinaciones_xrp.py: sube la precisión de 50.4%->61.6% en
# LARGO sobre XRP en 1h) en vez de solo RSI, manteniendo igual el resto
# de la regla (SMA200 obligatoria, cruce EMA como alternativa). Se aplica
# a las 4 monedas, aunque el análisis que lo respalda solo se hizo con
# datos de XRP - es una extrapolación, no algo validado por moneda.
USAR_GATILLO_TRIPLE = True
MFI_SOBREVENTA, MFI_SOBRECOMPRA = 20, 80

CAPITAL_TOTAL_COP = 10_000_000
FEE_SPOT = 0.0010     # 0.10% por lado (compra o venta) - usado en LARGO
FEE_FUTUROS = 0.0005  # 0.05% por lado - usado en CORTO

CONFIGS_SL_TP = {
    "actual (5% SL / 3% TP)": (5.0, 3.0),
    "1:1 (3% SL / 3% TP)": (3.0, 3.0),
}

# Tamaños de posición a barrer para encontrar el óptimo dado un capital
# fijo de $10,000,000 COP. Con la restricción de "una posición por moneda"
# (ver UNA_POSICION_POR_MONEDA), el máximo de posiciones simultáneas reales
# es 4 (una por símbolo) sin importar qué tan chico sea el tamaño - por eso
# se incluyen tamaños que representan 1/4, 1/2 y el 100% del capital.
TAMANOS_POSICION_COP = [500_000, 1_000_000, 1_500_000, 2_000_000,
                        2_500_000, 3_000_000, 5_000_000, 10_000_000]

# Vuelve a la restricción real de producción: no se puede tener dos
# posiciones abiertas a la vez en la misma moneda (evita apilar entradas
# correlacionadas mientras el RSI se mantiene en zona extrema varias
# corridas seguidas - eso fue lo que hundió el resultado al permitir
# reentradas libres).
UNA_POSICION_POR_MONEDA = True


def agregar_mfi_bollinger(df: pd.DataFrame) -> pd.DataFrame:
    """MFI(14) y Bollinger %B(20,2), no incluidos en add_indicators() de
    backtest_cron_gaps.py - se agregan acá para el gatillo triple."""
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]

    precio_tipico = (high + low + close) / 3
    flujo_dinero = precio_tipico * volume
    direccion = precio_tipico.diff()
    flujo_positivo = flujo_dinero.where(direccion > 0, 0.0).rolling(14).sum()
    flujo_negativo = flujo_dinero.where(direccion < 0, 0.0).rolling(14).sum()
    ratio_flujo = flujo_positivo / flujo_negativo
    df["mfi14"] = 100 - (100 / (1 + ratio_flujo))

    sma20, std20 = close.rolling(20).mean(), close.rolling(20).std()
    bb_lower, bb_upper = sma20 - 2 * std20, sma20 + 2 * std20
    df["bb_pct_b"] = (close - bb_lower) / (bb_upper - bb_lower)

    return df


def generar_senales(df: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    """Reproduce evaluar_senal() de producción (misma regla, mismo dedup de
    cruce), pero sin cooldown ni límite de capital - eso se aplica después,
    a nivel de portafolio."""
    senales = []
    ultimo_cruce_visto = None
    checkpoints = [i for i in range(WARMUP, len(df) - 1) if df.index[i].hour in CRON_DESPUES_HORAS_UTC]

    for i in checkpoints:
        cruce, cruce_ts = None, None
        for k in range(i - CRON_DESPUES_VENTANA + 1, i + 1):
            if k < 0 or pd.isna(df["cruce"].iloc[k]):
                continue
            cruce, cruce_ts = df["cruce"].iloc[k], df.index[k]

        if cruce_ts is not None and cruce_ts == ultimo_cruce_visto:
            cruce = None
        if cruce_ts is not None:
            ultimo_cruce_visto = cruce_ts

        row = df.iloc[i]
        trend = row["sma_trend"]
        if pd.isna(trend):
            continue

        if USAR_GATILLO_TRIPLE:
            sobreventa = (row["rsi"] < RSI_OVERSOLD) and (row["mfi14"] < MFI_SOBREVENTA) and (row["bb_pct_b"] < 0)
            sobrecompra = (row["rsi"] > RSI_OVERBOUGHT) and (row["mfi14"] > MFI_SOBRECOMPRA) and (row["bb_pct_b"] > 1)
        else:
            sobreventa = row["rsi"] < RSI_OVERSOLD
            sobrecompra = row["rsi"] > RSI_OVERBOUGHT

        direccion = None
        if row["close"] > trend and (sobreventa or cruce == "dorado"):
            direccion = "LARGO"
        elif row["close"] < trend and (sobrecompra or cruce == "muerte"):
            direccion = "CORTO"
        if direccion:
            senales.append((df.index[i], direccion))

    return senales


def simular_portafolio(dfs: dict[str, pd.DataFrame], senales_por_symbol: dict,
                        sl_pct: float, tp_pct: float, tamano_posicion_cop: float):
    """Simulación de portafolio con capital compartido de $5,000,000 COP y
    comisiones spot/futuros. Se puede reentrar en la misma moneda tantas
    veces como se quiera (posiciones concurrentes permitidas); el único
    límite para tomar una señal es tener `tamano_posicion_cop` libres en
    ese momento - si no hay, la señal se descarta.
    """
    capital_libre = CAPITAL_TOTAL_COP
    posiciones_abiertas = []  # lista de posiciones concurrentes (cualquier moneda)
    monedas_con_posicion = set()
    trades = []
    senales_perdidas_por_capital = 0
    senales_perdidas_por_posicion_abierta = 0

    senales_por_ts = {}
    for symbol, lista in senales_por_symbol.items():
        for ts, direccion in lista:
            senales_por_ts.setdefault(ts, []).append((symbol, direccion))

    todos_los_ts = sorted(set().union(*[set(df.index) for df in dfs.values()]))

    for ts in todos_los_ts:
        # 1) revisar cierres de posiciones abiertas en esta vela
        siguen_abiertas = []
        for pos in posiciones_abiertas:
            df = dfs[pos["symbol"]]
            if ts <= pos["entrada_ts"] or ts not in df.index:
                siguen_abiertas.append(pos)
                continue
            row = df.loc[ts]
            horas_transcurridas = (ts - pos["entrada_ts"]).total_seconds() / 3600

            hit_sl = (row["high"] >= pos["sl_precio"]) if pos["direccion"] == "CORTO" else (row["low"] <= pos["sl_precio"])
            hit_tp = (row["low"] <= pos["tp_precio"]) if pos["direccion"] == "CORTO" else (row["high"] >= pos["tp_precio"])

            resultado, precio_salida = None, None
            if hit_sl:
                resultado, precio_salida = "SL", pos["sl_precio"]
            elif hit_tp:
                resultado, precio_salida = "TP", pos["tp_precio"]
            elif horas_transcurridas >= MAX_HOLD_HOURS:
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
                "entrada_ts": pos["entrada_ts"], "salida_ts": ts,
                "horas_hasta_salida": round(horas_transcurridas, 1),
                "pnl_neto_cop": round(pnl_neto_cop),
            })
            monedas_con_posicion.discard(pos["symbol"])
        posiciones_abiertas = siguen_abiertas

        # 2) procesar señales nuevas en esta vela (orden fijo: XRP, ETH, DOGE, SOL)
        for symbol, direccion in senales_por_ts.get(ts, []):
            if UNA_POSICION_POR_MONEDA and symbol in monedas_con_posicion:
                senales_perdidas_por_posicion_abierta += 1
                continue
            if capital_libre < tamano_posicion_cop:
                senales_perdidas_por_capital += 1
                continue

            fee_rate = FEE_FUTUROS if direccion == "CORTO" else FEE_SPOT
            entrada_precio = dfs[symbol].loc[ts, "close"]
            fee_entrada_cop = tamano_posicion_cop * fee_rate

            capital_libre -= (tamano_posicion_cop + fee_entrada_cop)

            if direccion == "CORTO":
                sl_precio = entrada_precio * (1 + sl_pct / 100)
                tp_precio = entrada_precio * (1 - tp_pct / 100)
            else:
                sl_precio = entrada_precio * (1 - sl_pct / 100)
                tp_precio = entrada_precio * (1 + tp_pct / 100)

            posiciones_abiertas.append({
                "symbol": symbol, "direccion": direccion, "entrada_ts": ts, "entrada_precio": entrada_precio,
                "sl_precio": sl_precio, "tp_precio": tp_precio,
                "fee_rate": fee_rate, "fee_entrada_cop": fee_entrada_cop,
                "tamano_cop": tamano_posicion_cop,
            })
            monedas_con_posicion.add(symbol)

    # cerrar al final del histórico lo que siga abierto, al precio de cierre
    # del último dato disponible de cada moneda (mark-to-market, no es una
    # salida real por SL/TP/timeout)
    capital_en_posiciones_abiertas = 0
    for pos in posiciones_abiertas:
        ultimo_precio = dfs[pos["symbol"]]["close"].iloc[-1]
        if pos["direccion"] == "LARGO":
            retorno = (ultimo_precio - pos["entrada_precio"]) / pos["entrada_precio"]
        else:
            retorno = (pos["entrada_precio"] - ultimo_precio) / pos["entrada_precio"]
        capital_en_posiciones_abiertas += pos["tamano_cop"] * (1 + retorno)

    return (
        pd.DataFrame(trades),
        capital_libre,
        capital_en_posiciones_abiertas,
        senales_perdidas_por_capital,
        senales_perdidas_por_posicion_abierta,
    )


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    dfs = {}
    senales_por_symbol = {}
    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = add_indicators(df)
        if USAR_GATILLO_TRIPLE:
            df = agregar_mfi_bollinger(df)
        dfs[symbol] = df
        senales_por_symbol[symbol] = generar_senales(df)
        print(f"  {len(senales_por_symbol[symbol])} señales generadas (sin restricción de capital)")

    filas_barrido = []

    for nombre_config, (sl_pct, tp_pct) in CONFIGS_SL_TP.items():
        print("\n" + "=" * 78)
        print(f"BARRIDO DE TAMAÑO DE POSICIÓN | {nombre_config} | Capital {CAPITAL_TOTAL_COP:,.0f} COP")
        print("=" * 78)

        for tamano in TAMANOS_POSICION_COP:
            (trades, capital_libre, capital_abierto, perdidas_capital,
             perdidas_pos_abierta) = simular_portafolio(dfs, senales_por_symbol, sl_pct, tp_pct, tamano)

            capital_final = capital_libre + capital_abierto
            ganancia_neta = capital_final - CAPITAL_TOTAL_COP
            total = len(trades)
            wins = (trades["resultado"] == "TP").sum() if total else 0

            filas_barrido.append({
                "config_sl_tp": nombre_config,
                "tamano_posicion_cop": tamano,
                "cupos_maximos_teoricos": int(CAPITAL_TOTAL_COP // tamano),
                "trades": total,
                "win_rate_%": round(wins / total * 100, 1) if total else 0.0,
                "senales_perdidas_por_capital": perdidas_capital,
                "senales_perdidas_por_posicion_abierta": perdidas_pos_abierta,
                "capital_final_cop": round(capital_final),
                "ganancia_neta_cop": round(ganancia_neta),
                "ganancia_neta_%": round(ganancia_neta / CAPITAL_TOTAL_COP * 100, 2),
            })

    df_barrido = pd.DataFrame(filas_barrido)
    print("\n" + "=" * 100)
    print("RESUMEN DEL BARRIDO DE TAMAÑO DE POSICIÓN")
    print("=" * 100)
    print(df_barrido.to_string(index=False))

    print("\n" + "-" * 78)
    print("MEJOR TAMAÑO DE POSICIÓN POR CONFIGURACIÓN (mayor ganancia neta en COP)")
    print("-" * 78)
    for nombre_config in CONFIGS_SL_TP:
        sub = df_barrido[df_barrido["config_sl_tp"] == nombre_config]
        mejor = sub.loc[sub["ganancia_neta_cop"].idxmax()]
        print(f"{nombre_config} -> ${mejor['tamano_posicion_cop']:,.0f} COP por entrada "
              f"({mejor['ganancia_neta_%']:.2f}%, {mejor['trades']} trades)")

    df_barrido.to_csv("resultados_barrido_tamano_posicion.csv", index=False)
    print("\nGuardado: resultados_barrido_tamano_posicion.csv")


if __name__ == "__main__":
    main()
