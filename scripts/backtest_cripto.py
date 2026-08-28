"""
Backtest multi-cripto usando datos de Binance (gratis, historial largo -
sin el límite de 60 días de Yahoo Finance), probando el score combinado y
los 8 criterios individuales sobre las 10 criptomonedas top actuales,
desde el 1 de enero de 2026 hasta hoy.

Optimización importante: los indicadores (RSI, EMA, MACD, VWAP, Bollinger,
Momentum, ATR, volumen promedio) se calculan UNA SOLA VEZ sobre toda la
serie de datos, no recalculados en cada paso - son indicadores causales
(cada punto solo usa datos hasta ese momento por construcción propia de
la fórmula), así que el resultado es idéntico a recalcular desde cero en
cada vela, pero muchísimo más rápido. Se verificó esta equivalencia antes
de usarlo.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_cripto.py
    python scripts/backtest_cripto.py --inicio 2026-01-01
    python scripts/backtest_cripto.py --activos BTCUSDT,ETHUSDT
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines
from app.indicators.technical_indicators import agregar_todos_los_indicadores
from scoring import _atr_relativo, ATR_PCT_THRESHOLD

CRIPTOS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "TRXUSDT", "XMRUSDT", "DOGEUSDT", "ZECUSDT", "XLMUSDT",
]

UMBRAL_SENAL = 80
MIN_VELAS = 110
HORIZONTE_TIEMPO = timedelta(days=3)
MAX_VELAS_ABS = 900  # cripto opera 24/7: 3 días = 864 velas de 5 min
PASO_VELAS = 3

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000
OBJETIVO_PCT = 0.03
STOP_PCT = 0.02

CRITERIOS = ["RSI", "EMA", "VWAP", "MACD", "Volumen", "ATR", "Momentum", "Bollinger"]
PESOS = {"RSI": 10, "EMA": 10, "VWAP": 20, "MACD": 10, "Volumen": 15,
         "ATR": 5, "Momentum": 15, "Bollinger": 10}


def _calcular_indicadores_y_condiciones(data):
    """Calcula todos los indicadores UNA vez sobre toda la serie, y arma
    columnas booleanas (True/False) por cada criterio y el score total,
    para cada fila - sin recalcular nada en un loop."""

    ind = agregar_todos_los_indicadores(data)

    atr_pct = ind["ATR"] / ind["Close"] * 100

    cond = {}
    cond["RSI"] = ind["RSI"] > 50
    cond["EMA"] = ind["EMA9"] > ind["EMA21"]
    cond["VWAP"] = ind["Close"] > ind["VWAP"]
    cond["MACD"] = ind["MACD_12_26_9"] > ind["MACDs_12_26_9"]
    cond["Volumen"] = ind["Volume"] > ind["VOL_AVG"]
    cond["ATR"] = atr_pct > ATR_PCT_THRESHOLD
    cond["Momentum"] = ind["MOM14"] > 0
    cond["Bollinger"] = ind["Close"] > ind["BBU_20_2.0_2.0"]

    for nombre in CRITERIOS:
        cond[nombre] = cond[nombre].fillna(False)

    score = sum(cond[nombre].astype(int) * PESOS[nombre] for nombre in CRITERIOS) + 5

    return ind, cond, score


def _simular_resultado(data, idx_entrada, precio_entrada, objetivo_pct=OBJETIVO_PCT, stop_pct=STOP_PCT):
    objetivo = precio_entrada * (1 + objetivo_pct)
    stop = precio_entrada * (1 - stop_pct)
    ts_entrada = data.index[idx_entrada]
    fin = min(idx_entrada + MAX_VELAS_ABS, len(data))

    for i in range(idx_entrada + 1, fin):
        if data.index[i] - ts_entrada > HORIZONTE_TIEMPO:
            precio_final = float(data.iloc[i - 1]["Close"])
            return "SIN_RESOLVER", ((precio_final - precio_entrada) / precio_entrada) * 100

        vela = data.iloc[i]
        toco_obj = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_obj and toco_stop:
            return "PERDIO", -stop_pct * 100
        if toco_obj:
            return "GANO", objetivo_pct * 100
        if toco_stop:
            return "PERDIO", -stop_pct * 100

    precio_final = float(data.iloc[fin - 1]["Close"])
    return "SIN_RESOLVER", ((precio_final - precio_entrada) / precio_entrada) * 100


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


@dataclass
class Senal:
    symbol: str
    idx: int
    ts: object
    precio: float
    resultado: str
    variacion: float


def _generar_senales(symbol, data, score, cond):
    resultados = {nombre: [] for nombre in (["ScoreCombinado"] + CRITERIOS)}
    en_posicion_hasta = {nombre: -1 for nombre in resultados}

    n = len(data)

    for i in range(MIN_VELAS, n, PASO_VELAS):
        precio = float(data["Close"].iloc[i])
        if precio != precio:
            continue

        disparos = {"ScoreCombinado": score.iloc[i] >= UMBRAL_SENAL}
        for nombre in CRITERIOS:
            disparos[nombre] = bool(cond[nombre].iloc[i])

        for nombre, cumple in disparos.items():
            if not cumple or i <= en_posicion_hasta[nombre]:
                continue
            resultado, variacion = _simular_resultado(data, i, precio)
            resultados[nombre].append(Senal(symbol, i, data.index[i], precio, resultado, variacion))
            en_posicion_hasta[nombre] = i + MAX_VELAS_ABS

    return resultados


def _generar_aleatorias(symbol, data, cantidad, semilla):
    random.seed(semilla)
    indices = [i for i in range(MIN_VELAS, len(data) - 1) if data["Close"].iloc[i] == data["Close"].iloc[i]]
    if not indices or cantidad == 0:
        return []
    salidas = []
    for _ in range(cantidad):
        i = random.choice(indices)
        precio = float(data["Close"].iloc[i])
        resultado, variacion = _simular_resultado(data, i, precio)
        salidas.append(Senal(symbol, i, data.index[i], precio, resultado, variacion))
    return salidas


def _stats(lista):
    if not lista:
        return None
    netos = [_calcular_dinero(s.variacion) for s in lista]
    ganaron = sum(1 for s in lista if s.resultado == "GANO")
    perdieron = sum(1 for s in lista if s.resultado == "PERDIO")
    resueltas = ganaron + perdieron
    win_rate = (ganaron / resueltas * 100) if resueltas else 0.0
    return {
        "n": len(lista), "win_rate": win_rate,
        "neto_promedio": sum(netos) / len(netos), "neto_total": sum(netos),
        "ganaron": ganaron, "perdieron": perdieron,
    }


def correr(fecha_inicio_str, activos):
    fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    todas_por_nombre = {nombre: [] for nombre in (["ScoreCombinado"] + CRITERIOS)}
    datos_por_symbol = {}

    for symbol in activos:
        print(f"Descargando {symbol} desde Binance ({fecha_inicio_str} a hoy)...")

        try:
            data = obtener_klines(symbol, "5m", fecha_inicio)
        except Exception as e:
            print(f"  {symbol}: error irrecuperable ({type(e).__name__}: {e}), se omite")
            continue

        if data is None or len(data) < MIN_VELAS + 10:
            print(f"  {symbol}: sin datos suficientes, se omite")
            continue

        print(f"  {symbol}: {len(data)} velas, {data.index[0].strftime('%Y-%m-%d')} a "
              f"{data.index[-1].strftime('%Y-%m-%d')}")

        datos_por_symbol[symbol] = data

        ind, cond, score = _calcular_indicadores_y_condiciones(data)
        resultados = _generar_senales(symbol, data, score, cond)

        for nombre in todas_por_nombre:
            todas_por_nombre[nombre].extend(resultados[nombre])

    print()
    print("=" * 100)
    print("RESULTADOS: SCORE COMBINADO Y CADA CRITERIO, SOBRE LAS CRIPTOS")
    print("=" * 100)
    print(f"{'SEÑAL':18} {'N':>6} {'WIN RATE':>10} {'NETO PROM.':>15} {'NETO TOTAL':>18} {'VS. ALEATORIO':>18}")
    print("-" * 100)

    filas = []
    for nombre, lista in todas_por_nombre.items():
        stats = _stats(lista)
        if stats is None:
            filas.append((nombre, None, None))
            continue

        # Grupo de control: mismo N, repartido proporcionalmente por símbolo.
        # Reutiliza los datos ya descargados, no vuelve a llamar a Binance.
        por_symbol = {}
        for s in lista:
            por_symbol.setdefault(s.symbol, 0)
            por_symbol[s.symbol] += 1

        aleatorias = []
        for symbol, cantidad in por_symbol.items():
            aleatorias.extend(
                _generar_aleatorias(symbol, datos_por_symbol[symbol], cantidad, hash((nombre, symbol)) % 10000)
            )

        stats_random = _stats(aleatorias)
        filas.append((nombre, stats, stats_random))

    filas_validas = [f for f in filas if f[1] is not None]
    filas_validas.sort(key=lambda f: f[1]["neto_promedio"], reverse=True)
    filas_sin_datos = [f for f in filas if f[1] is None]

    for nombre, stats, stats_random in filas_validas + filas_sin_datos:
        if stats is None:
            print(f"{nombre:18} sin señales")
            continue
        vs_random = f"{stats_random['win_rate']:.1f}% (n={stats_random['n']})" if stats_random else "N/A"
        print(f"{nombre:18} {stats['n']:>6} {stats['win_rate']:>9.1f}% "
              f"${stats['neto_promedio']:>+14,.0f} ${stats['neto_total']:>+17,.0f} {vs_random:>18}")

    print("-" * 100)

    if filas_validas:
        n_total = sum(f[1]["n"] for f in filas_validas)
        if n_total < 30:
            print("⚠️  Muestra total menor a 30 - no es suficiente para conclusiones firmes.")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--activos", type=str, default=None)
    args = parser.parse_args()

    activos = args.activos.split(",") if args.activos else CRIPTOS

    correr(args.inicio, activos)