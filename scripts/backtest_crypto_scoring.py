"""
Backtest del CryptoScoringEngine sobre datos históricos reales de
Binance - solo lectura, no ejecuta ninguna operación real ni conecta
ninguna cuenta.

Alcance (decidido explícitamente): recalcula técnico + derivados en
cada punto histórico (sí tienen series reales completas en Binance).
Fundamental, sentimiento y macro quedan fijos en su valor neutral (15,
5, 5 respectivamente) - el mismo valor que usa el motor en vivo cuando
esas categorías no tienen datos, así que este backtest es una
aproximación conservadora, no el motor completo.

Reutiliza las MISMAS reglas de señal de app/scoring/technical_score.py
y app/scoring/derivatives_score.py (no las duplica) y el mismo cálculo
de confidence de app/scoring/confidence.py, aplicados a cortes
históricos (walk-forward) en vez de al estado actual.

Métrica: por cada señal LONG/SHORT que se hubiera disparado con los
umbrales actuales (score>=75 o <=35, confidence>=70%), se mira el
retorno 24h después y se marca "hit" si el precio se movió a favor de
la señal.

Uso: python -m scripts.backtest_crypto_scoring
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
from loguru import logger

from app.derivatives.crypto_derivatives import _partir_en_mitades, _tendencia
from app.providers.binance_provider import BinanceProvider, BinanceProviderError
from app.scoring.confidence import calcular_confidence
from app.scoring.derivatives_score import (
    PUNTOS_TOTALES as DERIVADOS_PUNTOS_TOTALES,
    _senal_funding_rate,
    _senal_long_short_ratio,
    _senal_oi_precio,
)
from app.scoring.metric_types import puntaje_categoria
from app.scoring.technical_score import (
    PESOS_TIMEFRAME,
    PUNTOS_TOTALES as TECNICO_PUNTOS_TOTALES,
    VELAS_MINIMAS,
    _estructura_ema,
    _senal_macd,
    _senal_rsi,
    _senal_soporte_resistencia,
    _senal_volumen,
)
from scripts.binance_data import obtener_klines

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]
DIAS_BACKTEST = 30
DIAS_LOOKBACK_EXTRA = 45  # margen para EMA200 en 4h antes de que arranque la ventana de prueba
PASO_HORAS = 4
HORIZONTE_HORAS = 24  # cuánto se mira "hacia adelante" para medir hit/miss

SCORE_FUNDAMENTAL_FIJO = 15.0  # 30 * 0.5, igual que el "neutral" del motor en vivo
SCORE_SENTIMIENTO_FIJO = 5.0   # 10 * 0.5
SCORE_MACRO_FIJO = 5.0         # 10 * 0.5
PUNTOS_TOTALES_POR_CATEGORIA = {"fundamental": 30, "tecnico": 30, "derivados": 20, "sentimiento": 10, "macro": 10}

UMBRAL_LONG_SCORE = 75
UMBRAL_SHORT_SCORE = 35
UMBRAL_CONFIDENCE = 70

# Si se deja en None, la ventana de prueba termina "ahora" (comportamiento
# original). Si se fija una fecha, la ventana de DIAS_BACKTEST días
# termina en esa fecha en vez de en el momento de la corrida - permite
# repetir el backtest sobre un mes específico ya cerrado.
FECHA_FIN_VENTANA = datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc)

VENTANA_TENDENCIA = 30  # mismo tamaño de ventana que usa el motor en vivo para OI/precio


def _fetch_ohlcv(symbol: str, interval: str) -> pd.DataFrame:
    fecha_fin = FECHA_FIN_VENTANA or datetime.now(timezone.utc)
    fecha_inicio = fecha_fin - timedelta(days=DIAS_BACKTEST + DIAS_LOOKBACK_EXTRA)
    logger.info(f"Descargando histórico {symbol} {interval}...")
    df = obtener_klines(symbol, interval, fecha_inicio, fecha_fin)
    if df is None or df.empty:
        raise RuntimeError(f"Sin datos históricos para {symbol} {interval}")
    logger.info(f"OK: {len(df)} velas descargadas para {symbol} {interval}")
    return df


def _serie_desde_historial(historial: list[dict], clave_tiempo: str, clave_valor: str) -> pd.Series:
    return pd.Series({item[clave_tiempo]: item[clave_valor] for item in historial}).sort_index()


def _evaluar_timeframe(df: pd.DataFrame, corte: pd.Timestamp) -> dict | None:
    ventana = df.loc[:corte].tail(VELAS_MINIMAS)
    if len(ventana) < VELAS_MINIMAS:
        return None

    metricas = [
        {"metrica": "estructura_ema", "senal": _estructura_ema(ventana)},
        {"metrica": "rsi", "senal": _senal_rsi(ventana)},
        {"metrica": "macd", "senal": _senal_macd(ventana)},
        {"metrica": "soporte_resistencia", "senal": _senal_soporte_resistencia(ventana)},
        {"metrica": "volumen", "senal": _senal_volumen(ventana)},
        {"metrica": "atr", "senal": "neutral"},
    ]
    return puntaje_categoria(metricas, 1.0)


def _score_tecnico_historico(dfs_por_timeframe: dict, corte: pd.Timestamp) -> dict:
    por_timeframe = {}
    for interval in PESOS_TIMEFRAME:
        resultado = _evaluar_timeframe(dfs_por_timeframe[interval], corte)
        por_timeframe[interval] = resultado or {"puntos": None, "disponible": False, "cobertura": 0.0, "metricas": []}

    disponibles = {tf: r for tf, r in por_timeframe.items() if r["disponible"]}
    if not disponibles:
        return {"puntos": None, "disponible": False, "cobertura": 0.0, "por_timeframe": por_timeframe}

    peso_total = sum(PESOS_TIMEFRAME[tf] for tf in disponibles)
    fraccion = sum((PESOS_TIMEFRAME[tf] / peso_total) * disponibles[tf]["puntos"] for tf in disponibles)

    return {
        "puntos": round(fraccion * TECNICO_PUNTOS_TOTALES, 4),
        "disponible": True,
        "cobertura": sum(r["cobertura"] for r in disponibles.values()) / len(disponibles),
        "por_timeframe": por_timeframe,
    }


def _asof_seguro(serie: pd.Series, corte: pd.Timestamp):
    """serie.asof() puede fallar o no tener sentido sobre una serie
    vacía (ej. open interest/long-short ratio fuera de los ~30 días que
    Binance retiene) - en ese caso se trata como sin dato, no como error."""
    if serie.empty:
        return None
    return serie.asof(corte)


def _score_derivados_historico(funding_serie, oi_serie, ls_serie, precios_4h, corte: pd.Timestamp) -> dict:
    metricas = []

    funding_actual = _asof_seguro(funding_serie, corte)
    metricas.append({"metrica": "funding_rate",
                      "senal": _senal_funding_rate(funding_actual) if pd.notna(funding_actual) else "sin_datos"})

    oi_ventana = oi_serie.loc[:corte].tail(VENTANA_TENDENCIA)
    precio_ventana = precios_4h.loc[:corte].tail(VENTANA_TENDENCIA)
    if len(oi_ventana) >= 2 and len(precio_ventana) >= 2:
        oi_previos, oi_recientes = _partir_en_mitades(oi_ventana.tolist())
        oi_tendencia = _tendencia(sum(oi_recientes) / len(oi_recientes), sum(oi_previos) / len(oi_previos))
        p_previos, p_recientes = _partir_en_mitades(precio_ventana.tolist())
        precio_tendencia = _tendencia(sum(p_recientes) / len(p_recientes), sum(p_previos) / len(p_previos))
        metricas.append({"metrica": "oi_precio_volumen", "senal": _senal_oi_precio(oi_tendencia, precio_tendencia)})
    else:
        metricas.append({"metrica": "oi_precio_volumen", "senal": "sin_datos"})

    ls_actual = _asof_seguro(ls_serie, corte)
    metricas.append({"metrica": "long_short_ratio",
                      "senal": _senal_long_short_ratio(ls_actual) if pd.notna(ls_actual) else "sin_datos"})

    # liquidaciones: el endpoint de Binance devuelve 404 en producción
    # (ver Fase 7) - se mantiene neutral igual que el comportamiento real
    metricas.append({"metrica": "liquidaciones", "senal": "neutral"})

    return puntaje_categoria(metricas, DERIVADOS_PUNTOS_TOTALES)


def _categoria_fija(puntos: float, maximo: float) -> dict:
    return {"puntos": puntos, "disponible": True, "cobertura": 1.0,
            "metricas": [{"metrica": "fijo_neutral", "senal": "neutral", "fuente": "backtest"}]}


def _determinar_senal(total_score: float, confidence: float) -> str:
    if total_score >= UMBRAL_LONG_SCORE and confidence >= UMBRAL_CONFIDENCE:
        return "LONG"
    if total_score <= UMBRAL_SHORT_SCORE and confidence >= UMBRAL_CONFIDENCE:
        return "SHORT"
    return "NO_OPERAR"


def backtest_symbol(symbol: str, provider: BinanceProvider) -> list[dict]:
    dfs = {interval: _fetch_ohlcv(symbol, interval) for interval in PESOS_TIMEFRAME}

    fecha_fin = FECHA_FIN_VENTANA or datetime.now(timezone.utc)
    fecha_inicio_funding = fecha_fin - timedelta(days=DIAS_BACKTEST + VENTANA_TENDENCIA)
    funding_hist = provider.get_funding_rate_history(
        symbol, limit=1000, start_time=fecha_inicio_funding, end_time=fecha_fin
    )
    funding_serie = _serie_desde_historial(funding_hist, "funding_time", "funding_rate")

    # Open interest y long/short ratio: Binance solo guarda ~30 días de
    # historial para estos dos endpoints (a diferencia de funding rate) -
    # si la ventana pedida es más vieja que eso, simplemente no hay datos
    # y el sistema los marca "sin_datos" (no penaliza, ya está manejado
    # por puntaje_categoria) en vez de fallar.
    try:
        oi_hist = provider.get_open_interest_history(symbol, period="4h", limit=200)
        oi_serie = _serie_desde_historial(oi_hist, "time", "open_interest")
    except BinanceProviderError as e:
        logger.warning(f"Sin historial de open interest disponible para {symbol} en esta ventana: {e}")
        oi_serie = pd.Series(dtype=float)

    try:
        ls_hist = provider.get_long_short_ratio(symbol, period="4h", limit=200)
        ls_serie = _serie_desde_historial(ls_hist, "time", "long_short_ratio")
    except BinanceProviderError as e:
        logger.warning(f"Sin historial de long/short ratio disponible para {symbol} en esta ventana: {e}")
        ls_serie = pd.Series(dtype=float)

    precios_4h = dfs["4h"]["Close"]

    inicio_ventana = dfs["4h"].index[-1] - timedelta(days=DIAS_BACKTEST)
    cortes = dfs["4h"].index[dfs["4h"].index >= inicio_ventana]
    cortes = cortes[::max(1, PASO_HORAS // 4)]  # los datos ya vienen en velas de 4h

    resultados = []
    for corte in cortes:
        tecnico = _score_tecnico_historico(dfs, corte)
        derivados = _score_derivados_historico(funding_serie, oi_serie, ls_serie, precios_4h, corte)

        score_tecnico = tecnico["puntos"] if tecnico["disponible"] else TECNICO_PUNTOS_TOTALES * 0.5
        score_derivados = derivados["puntos"] if derivados["disponible"] else DERIVADOS_PUNTOS_TOTALES * 0.5

        total_score = SCORE_FUNDAMENTAL_FIJO + score_tecnico + score_derivados + SCORE_SENTIMIENTO_FIJO + SCORE_MACRO_FIJO

        categorias = {
            "fundamental": _categoria_fija(SCORE_FUNDAMENTAL_FIJO, 30),
            "tecnico": tecnico,
            "derivados": derivados,
            "sentimiento": _categoria_fija(SCORE_SENTIMIENTO_FIJO, 10),
            "macro": _categoria_fija(SCORE_MACRO_FIJO, 10),
        }
        confidence = calcular_confidence(categorias, PUNTOS_TOTALES_POR_CATEGORIA)["confidence"]

        signal = _determinar_senal(total_score, confidence)

        entry_price = float(precios_4h.asof(corte))
        salida_ts = corte + timedelta(hours=HORIZONTE_HORAS)
        precios_futuros = precios_4h.loc[precios_4h.index >= salida_ts]
        exit_price = float(precios_futuros.iloc[0]) if len(precios_futuros) else None

        retorno_pct = None
        hit = None
        if exit_price is not None and signal != "NO_OPERAR":
            retorno_pct = (exit_price - entry_price) / entry_price * 100
            hit = (signal == "LONG" and retorno_pct > 0) or (signal == "SHORT" and retorno_pct < 0)

        resultados.append({
            "symbol": symbol, "timestamp": corte, "total_score": round(total_score, 2),
            "confidence": round(confidence, 2), "signal": signal, "entry_price": entry_price,
            "exit_price": exit_price, "retorno_pct": retorno_pct, "hit": hit,
        })

    return resultados


def _resumir(resultados: list[dict], symbol: str):
    de_este_symbol = [r for r in resultados if r["symbol"] == symbol]
    print(f"\n=== {symbol} ({len(de_este_symbol)} puntos evaluados, últimos {DIAS_BACKTEST} días) ===")

    for direccion in ("LONG", "SHORT"):
        señales = [r for r in de_este_symbol if r["signal"] == direccion and r["hit"] is not None]
        if not señales:
            print(f"{direccion}: 0 señales disparadas")
            continue
        aciertos = sum(1 for r in señales if r["hit"])
        retorno_prom = sum(r["retorno_pct"] for r in señales) / len(señales)
        print(
            f"{direccion}: {len(señales)} señales | hit rate = {aciertos}/{len(señales)} "
            f"({aciertos / len(señales) * 100:.1f}%) | retorno promedio {HORIZONTE_HORAS}h = {retorno_prom:+.2f}%"
        )

    no_operar = sum(1 for r in de_este_symbol if r["signal"] == "NO_OPERAR")
    print(f"NO_OPERAR: {no_operar}/{len(de_este_symbol)} puntos ({no_operar / len(de_este_symbol) * 100:.1f}%)")


def backtest_crypto_scoring():
    provider = BinanceProvider()
    todos_los_resultados = []

    for symbol in SIMBOLOS:
        try:
            resultados = backtest_symbol(symbol, provider)
            todos_los_resultados.extend(resultados)
        except BinanceProviderError as e:
            logger.error(f"No se pudo completar el backtest de {symbol}: {e}")

    for symbol in SIMBOLOS:
        _resumir(todos_los_resultados, symbol)


if __name__ == "__main__":
    backtest_crypto_scoring()
