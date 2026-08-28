"""
Backtest de estrategias de SCALPING de reversión a la media para cripto -
distinto a todo lo probado antes (que era momentum: comprar cuando ya
estaba subiendo). Aquí se prueba lo opuesto: comprar cuando el precio
está "estirado" hacia abajo, apostando al rebote de corto plazo.

Estrategias:
  - RSI_Sobreventa: RSI(14) < 30
  - BollingerInferior: precio toca o cruza la banda inferior de Bollinger
  - VWAP_Reversion: precio se aleja del VWAP hacia abajo y la vela actual
    cierra de vuelta por encima de él (rebote)

Escala de scalping real (no de 3 días):
  - Objetivo/stop pequeños (configurable, default +0.6% / -0.4%)
  - Horizonte corto (default 2 horas, no días)

Usa datos de Binance de los últimos 4 meses (configurable).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_scalping_cripto.py
    python scripts/backtest_scalping_cripto.py --meses 4
    python scripts/backtest_scalping_cripto.py --objetivo 0.006 --stop 0.004 --horas 2
"""

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas_ta as ta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

CRIPTOS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "TRXUSDT", "DOGEUSDT", "ZECUSDT", "XLMUSDT",
]

MIN_VELAS = 60
PASO_VELAS = 2

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

ESTRATEGIAS = ["RSI_Sobreventa", "BollingerInferior", "VWAP_Reversion"]


def _calcular_indicadores_y_condiciones(data):
    rsi = ta.rsi(data["Close"], length=14)
    bb = ta.bbands(data["Close"], length=20)
    vwap = ta.vwap(data["High"], data["Low"], data["Close"], data["Volume"])

    cond = {}
    cond["RSI_Sobreventa"] = (rsi < 30).fillna(False)

    if bb is not None:
        bbl = bb["BBL_20_2.0_2.0"]
        bbu = bb["BBU_20_2.0_2.0"]
        ancho_real = (bbu - bbl) > 0  # evita el caso de varianza cero (bandas colapsadas)
        cond["BollingerInferior"] = ((data["Close"] <= bbl) & ancho_real).fillna(False)
    else:
        cond["BollingerInferior"] = (data["Close"] * 0).astype(bool)

    if vwap is not None:
        alejado_abajo = data["Close"].shift(1) < vwap.shift(1) * 0.995  # se alejó >0.5% por debajo
        cerro_de_vuelta = data["Close"] > vwap
        cond["VWAP_Reversion"] = (alejado_abajo & cerro_de_vuelta).fillna(False)
    else:
        cond["VWAP_Reversion"] = (data["Close"] * 0).astype(bool)

    return cond


def _simular_resultado(data, idx_entrada, precio_entrada, objetivo_pct, stop_pct, horizonte, max_velas_abs):
    objetivo = precio_entrada * (1 + objetivo_pct)
    stop = precio_entrada * (1 - stop_pct)
    ts_entrada = data.index[idx_entrada]
    fin = min(idx_entrada + max_velas_abs, len(data))

    for i in range(idx_entrada + 1, fin):
        if data.index[i] - ts_entrada > horizonte:
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


def _generar_senales(symbol, data, cond, objetivo_pct, stop_pct, horizonte, max_velas_abs):
    resultados = {nombre: [] for nombre in ESTRATEGIAS}
    en_posicion_hasta = {nombre: -1 for nombre in ESTRATEGIAS}

    for i in range(MIN_VELAS, len(data), PASO_VELAS):
        precio = float(data["Close"].iloc[i])
        if precio != precio:
            continue

        for nombre in ESTRATEGIAS:
            if not bool(cond[nombre].iloc[i]) or i <= en_posicion_hasta[nombre]:
                continue
            resultado, variacion = _simular_resultado(
                data, i, precio, objetivo_pct, stop_pct, horizonte, max_velas_abs
            )
            resultados[nombre].append(Senal(symbol, i, data.index[i], precio, resultado, variacion))
            en_posicion_hasta[nombre] = i + max_velas_abs

    return resultados


def _generar_aleatorias(data, cantidad, semilla, objetivo_pct, stop_pct, horizonte, max_velas_abs):
    random.seed(semilla)
    indices = [i for i in range(MIN_VELAS, len(data) - 1) if data["Close"].iloc[i] == data["Close"].iloc[i]]
    if not indices or cantidad == 0:
        return []
    salidas = []
    for _ in range(cantidad):
        i = random.choice(indices)
        precio = float(data["Close"].iloc[i])
        resultado, variacion = _simular_resultado(data, i, precio, objetivo_pct, stop_pct, horizonte, max_velas_abs)
        salidas.append(Senal("RANDOM", i, data.index[i], precio, resultado, variacion))
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
    }


def correr(meses, objetivo_pct, stop_pct, horas, activos):
    horizonte = timedelta(hours=horas)
    max_velas_abs = int((horas * 60) / 5) + 50  # velas de 5 min que caben en el horizonte, + margen

    fecha_inicio = datetime.now(timezone.utc) - timedelta(days=meses * 30)

    print(f"Período: últimos {meses} meses (desde {fecha_inicio.strftime('%Y-%m-%d')})")
    print(f"Regla de salida (scalping): objetivo +{objetivo_pct*100:.2f}% / stop -{stop_pct*100:.2f}% "
          f"/ horizonte {horas}h")
    print()

    todas_por_nombre = {nombre: [] for nombre in ESTRATEGIAS}
    datos_por_symbol = {}

    for symbol in activos:
        print(f"Descargando {symbol}...")
        try:
            data = obtener_klines(symbol, "5m", fecha_inicio)
        except Exception as e:
            print(f"  {symbol}: error irrecuperable ({type(e).__name__}), se omite")
            continue

        if data is None or len(data) < MIN_VELAS + 10:
            print(f"  {symbol}: sin datos suficientes, se omite")
            continue

        print(f"  {symbol}: {len(data)} velas")
        datos_por_symbol[symbol] = data

        cond = _calcular_indicadores_y_condiciones(data)
        resultados = _generar_senales(symbol, data, cond, objetivo_pct, stop_pct, horizonte, max_velas_abs)

        for nombre in todas_por_nombre:
            todas_por_nombre[nombre].extend(resultados[nombre])

    print()
    print("=" * 100)
    print("RESULTADOS: ESTRATEGIAS DE SCALPING (REVERSIÓN A LA MEDIA)")
    print("=" * 100)
    print(f"{'ESTRATEGIA':20} {'N':>6} {'WIN RATE':>10} {'NETO PROM.':>15} {'NETO TOTAL':>18} {'VS. ALEATORIO':>18}")
    print("-" * 100)

    filas = []
    for nombre, lista in todas_por_nombre.items():
        stats = _stats(lista)
        if stats is None:
            filas.append((nombre, None, None))
            continue

        por_symbol = {}
        for s in lista:
            por_symbol.setdefault(s.symbol, 0)
            por_symbol[s.symbol] += 1

        aleatorias = []
        for symbol, cantidad in por_symbol.items():
            aleatorias.extend(_generar_aleatorias(
                datos_por_symbol[symbol], cantidad, hash((nombre, symbol)) % 10000,
                objetivo_pct, stop_pct, horizonte, max_velas_abs
            ))

        stats_random = _stats(aleatorias)
        filas.append((nombre, stats, stats_random))

    filas_validas = [f for f in filas if f[1] is not None]
    filas_validas.sort(key=lambda f: f[1]["neto_promedio"], reverse=True)

    for nombre, stats, stats_random in filas_validas:
        vs_random = f"{stats_random['win_rate']:.1f}% (n={stats_random['n']})" if stats_random else "N/A"
        print(f"{nombre:20} {stats['n']:>6} {stats['win_rate']:>9.1f}% "
              f"${stats['neto_promedio']:>+14,.0f} ${stats['neto_total']:>+17,.0f} {vs_random:>18}")

    print("-" * 100)

    n_total = sum(f[1]["n"] for f in filas_validas) if filas_validas else 0
    if n_total < 30:
        print("⚠️  Muestra total menor a 30 - no es suficiente para conclusiones firmes.")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--meses", type=int, default=4)
    parser.add_argument("--objetivo", type=float, default=0.006)
    parser.add_argument("--stop", type=float, default=0.004)
    parser.add_argument("--horas", type=float, default=2.0)
    parser.add_argument("--activos", type=str, default=None)
    args = parser.parse_args()

    activos = args.activos.split(",") if args.activos else CRIPTOS

    correr(args.meses, args.objetivo, args.stop, args.horas, activos)