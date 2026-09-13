"""
Análisis de integración entre crypto-alerts/analyze_and_notify.py (el
sistema que ya validamos y está en producción) y app/scoring/
crypto_scoring_engine.py ("RobotinaIA Crypto", el otro sistema que envía
al mismo chat de Telegram).

IMPORTANTE - qué SÍ y qué NO se puede backtestear acá:

CryptoScoringEngine combina 5 categorías: fundamental (30 pts),
técnico (30 pts), derivados (20 pts), sentimiento (10 pts), macro
(10 pts). Con capital histórico disponible en este backtest (solo velas
OHLCV de Binance), únicamente el componente TÉCNICO es reproducible -
fundamental necesita on-chain/DeFiLlama/CoinGecko históricos, derivados
necesita funding rate/open interest históricos, sentimiento necesita el
histórico del Fear&Greed Index, y macro necesita datos macro - ninguno
de esos se descarga acá.

Dato revelador de la propia fórmula: si esas 4 categorías quedan en su
valor neutral (50%, que es justo lo que hace el motor cuando le faltan
datos), el score total queda fijo en 35 puntos + el score técnico
(0-30) = rango 35-65. Los umbrales de señal son >=75 (LONG) y <=35
(SHORT) - o sea, **sin fundamental/derivados/sentimiento/macro, el
sistema NUNCA podría generar LONG y solo generaría SHORT en el límite
exacto (score técnico=0)**. Por eso no tiene sentido "backtestear la
señal LONG/SHORT completa del scoring engine" con lo que hay disponible
acá - se haría trampa (simularíamos un escenario que el propio motor no
permite).

Lo que SÍ se puede hacer honestamente: reproducir la REGLA TÉCNICA
(simplificada a 1h, la propia fórmula combina 4h/1h/15m con pesos
40/40/20 - acá solo se usa 1h para que encaje con el resto del
backtest) y usarla como FILTRO DE CONFIRMACIÓN adicional sobre las
señales ya validadas de analyze_and_notify.py: exigir que la lectura
técnica (estructura EMA20/50/200, RSI>55/<45, MACD, soporte/resistencia)
no contradiga la dirección de la señal. Esto prueba si "integrar" los
dos sistemas ayuda o estorba, sin fingir que se backtesteó algo que en
realidad no se puede reproducir históricamente.

Uso:
    pip install -r requirements.txt
    python analisis_integracion_robotina.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd

from backtest_cron_gaps import (
    EXCHANGE_ID, SYMBOLS, TIMEFRAME, LOOKBACK_DAYS, WARMUP,
    CRON_DESPUES_HORAS_UTC, CRON_DESPUES_VENTANA, RSI_OVERSOLD, RSI_OVERBOUGHT,
    fetch_ohlcv_full, add_indicators,
)
from backtest_portafolio import (
    CAPITAL_TOTAL_COP, MFI_SOBREVENTA, agregar_mfi_bollinger, simular_portafolio,
)

TAMANO_POSICION_COP = 500_000
SL_PCT, TP_PCT = 3.5, 1.5

LOOKBACK_SOPORTE_RESISTENCIA = 20


def agregar_columnas_tecnico_robotina(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce (simplificado a 1h) las 4 métricas direccionales del
    score técnico de RobotinaIA Crypto (app/scoring/technical_score.py):
    estructura EMA20/50/200, RSI>55/<45, MACD línea vs señal,
    soporte/resistencia de 20 velas. Volumen y ATR se omiten (volumen no
    tiene lectura propia sin precio, ATR siempre es neutral - no aportan
    dirección)."""
    close = df["close"]

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    estructura_favorable = (close > ema20) & (ema20 > ema50) & (ema50 > ema200)
    estructura_desfavorable = (close < ema20) & (ema20 < ema50) & (ema50 < ema200)

    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    resistencia = df["high"].shift(1).rolling(LOOKBACK_SOPORTE_RESISTENCIA).max()
    soporte = df["low"].shift(1).rolling(LOOKBACK_SOPORTE_RESISTENCIA).min()

    direccion = pd.Series(0, index=df.index)
    direccion += estructura_favorable.astype(int) - estructura_desfavorable.astype(int)
    direccion += (df["rsi"] > 55).astype(int) - (df["rsi"] < 45).astype(int)
    direccion += (macd_line > macd_signal).astype(int) - (macd_line < macd_signal).astype(int)
    direccion += (close > resistencia).astype(int) - (close < soporte).astype(int)

    df["tecnico_direccion"] = direccion  # rango -4 (muy bajista) a +4 (muy alcista)
    return df


def generar_senales_integrado(df: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    """Misma regla validada de producción (gatillo triple LARGO / RSI
    solo CORTO, sin cruce EMA), con un filtro adicional: la lectura
    técnica de RobotinaIA Crypto no puede contradecir la dirección."""
    senales = []
    checkpoints = [i for i in range(WARMUP, len(df) - 1) if df.index[i].hour in CRON_DESPUES_HORAS_UTC]

    for i in checkpoints:
        row = df.iloc[i]
        trend = row["sma_trend"]
        if pd.isna(trend):
            continue

        sobreventa_triple = (row["rsi"] < RSI_OVERSOLD) and (row["mfi14"] < MFI_SOBREVENTA) and (row["bb_pct_b"] < 0)
        sobrecompra = row["rsi"] > RSI_OVERBOUGHT
        tecnico = row["tecnico_direccion"]

        direccion = None
        if row["close"] > trend and sobreventa_triple and tecnico >= 0:
            direccion = "LARGO"
        elif row["close"] < trend and sobrecompra and tecnico <= 0:
            direccion = "CORTO"
        if direccion:
            senales.append((df.index[i], direccion))

    return senales


def resumen(trades: pd.DataFrame, capital_libre: float, capital_abierto: float) -> dict:
    capital_final = capital_libre + capital_abierto
    total = len(trades)
    wins = (trades["resultado"] == "TP").sum() if total else 0
    return {
        "trades": total,
        "win_rate_%": round(wins / total * 100, 1) if total else 0.0,
        "ganancia_neta_cop": round(capital_final - CAPITAL_TOTAL_COP),
        "ganancia_neta_%": round((capital_final - CAPITAL_TOTAL_COP) / CAPITAL_TOTAL_COP * 100, 2),
    }


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    dfs = {}
    senales_solas = {}
    senales_integradas = {}

    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = add_indicators(df)
        df = agregar_mfi_bollinger(df)
        df = agregar_columnas_tecnico_robotina(df)
        dfs[symbol] = df

        from backtest_portafolio import generar_senales as generar_senales_solo
        senales_solas[symbol] = generar_senales_solo(df)
        senales_integradas[symbol] = generar_senales_integrado(df)

    print("\n" + "=" * 90)
    print("SEÑALES POR MONEDA: SOLO analyze_and_notify.py vs INTEGRADO (+ filtro técnico RobotinaIA)")
    print("=" * 90)
    for symbol in SYMBOLS:
        print(f"{symbol}: {len(senales_solas[symbol])} solas -> {len(senales_integradas[symbol])} integradas "
              f"(descartadas por contradicción técnica: {len(senales_solas[symbol]) - len(senales_integradas[symbol])})")

    trades_solo, cap_libre_solo, cap_abierto_solo, _, _ = simular_portafolio(
        dfs, senales_solas, SL_PCT, TP_PCT, TAMANO_POSICION_COP
    )
    trades_int, cap_libre_int, cap_abierto_int, _, _ = simular_portafolio(
        dfs, senales_integradas, SL_PCT, TP_PCT, TAMANO_POSICION_COP
    )

    r_solo = resumen(trades_solo, cap_libre_solo, cap_abierto_solo)
    r_int = resumen(trades_int, cap_libre_int, cap_abierto_int)

    print("\n" + "=" * 90)
    print(f"COMPARACIÓN (SL {SL_PCT}% / TP {TP_PCT}% / ${TAMANO_POSICION_COP:,.0f} COP por entrada)")
    print("=" * 90)
    print(pd.DataFrame([
        {"estrategia": "SOLO analyze_and_notify.py (baseline)", **r_solo},
        {"estrategia": "INTEGRADO (+ filtro técnico RobotinaIA)", **r_int},
    ]).to_string(index=False))

    trades_int.to_csv("resultados_integracion_robotina.csv", index=False)


if __name__ == "__main__":
    main()
