"""
Backtest histórico multi-día.

Recorre semanas de datos de 5 minutos, simulando en cada punto lo que el
sistema real habría visto (sin look-ahead), detecta cada vez que el score
habría cruzado el umbral, y simula si esa señal llega al objetivo (+3%)
o al stop (-1%) primero - igual que el trailing stop real inicial.

Compara contra un grupo de control de entradas ALEATORIAS (mismo stop y
objetivo, pero sin usar el score), para saber si el score realmente aporta
algo por encima del azar, no solo si "acertó".

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_historico.py
    python scripts/backtest_historico.py --dias 60
    python scripts/backtest_historico.py --activos AAPL,MINEROS.CL,BTC-USD
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings
from scoring import calcular_score, STOP_INICIAL_PCT, OBJETIVO_INICIAL_PCT

TZ_BOGOTA = ZoneInfo("America/Bogota")

MIN_VELAS_PARA_SCORE = 40   # lookback mínimo para que los indicadores no vengan vacíos
MAX_VELAS_SIMULACION = 200  # horizonte máximo para resolver una señal (~200 velas de 5 min)
PASO_VELAS = 3              # revisar cada 3 velas (~15 min, igual al intervalo real del scheduler)


@dataclass
class ResultadoSenal:
    symbol: str
    entrada_ts: object
    entrada_precio: float
    score: int
    resultado: str  # "GANO", "PERDIO", "SIN_RESOLVER"
    variacion_pct: float
    velas_hasta_resolver: int


def _cargar_datos(symbol, dias):
    data = yf.Ticker(symbol).history(period=f"{dias}d", interval="5m")
    if data.empty:
        return None
    data.index = data.index.tz_convert(TZ_BOGOTA)
    return data


def _simular_resultado(data, idx_entrada, precio_entrada):
    """Desde el punto de entrada, camina hacia adelante viendo si toca
    el objetivo (+3%) o el stop (-1%) primero, usando High/Low intrabar."""

    objetivo = precio_entrada * (1 + OBJETIVO_INICIAL_PCT)
    stop = precio_entrada * (1 - STOP_INICIAL_PCT)

    fin = min(idx_entrada + MAX_VELAS_SIMULACION, len(data))

    for i in range(idx_entrada + 1, fin):
        vela = data.iloc[i]

        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_objetivo and toco_stop:
            # No sabemos el orden exacto dentro de la misma vela - criterio
            # conservador: se cuenta como pérdida.
            return "PERDIO", -STOP_INICIAL_PCT * 100, i - idx_entrada
        if toco_objetivo:
            return "GANO", OBJETIVO_INICIAL_PCT * 100, i - idx_entrada
        if toco_stop:
            return "PERDIO", -STOP_INICIAL_PCT * 100, i - idx_entrada

    precio_final = float(data.iloc[fin - 1]["Close"])
    variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
    return "SIN_RESOLVER", variacion, fin - idx_entrada - 1


def _generar_senales_reales(symbol, data):
    """Recorre las velas simulando el scoring en vivo (cero look-ahead), y
    arma la lista de señales que realmente se habrían disparado, respetando
    que solo hay una señal activa a la vez por activo (igual que
    existe_senal_pendiente en el sistema real)."""

    senales = []
    en_posicion_hasta = -1

    for i in range(MIN_VELAS_PARA_SCORE, len(data), PASO_VELAS):
        if i <= en_posicion_hasta:
            continue

        data_hasta_aqui = data.iloc[: i + 1]

        try:
            score, precio = calcular_score(data_hasta_aqui)
        except Exception:
            continue

        if score >= Settings.UMBRAL_SENAL:
            resultado, variacion, velas = _simular_resultado(data, i, precio)

            senales.append(ResultadoSenal(
                symbol=symbol, entrada_ts=data.index[i], entrada_precio=precio,
                score=score, resultado=resultado, variacion_pct=variacion,
                velas_hasta_resolver=velas,
            ))

            en_posicion_hasta = i + velas

    return senales


def _generar_senales_aleatorias(symbol, data, cantidad, semilla):
    """Grupo de control: la misma cantidad de 'entradas' pero en momentos
    aleatorios, no basados en el score."""

    random.seed(semilla)
    senales = []

    indices_disponibles = list(range(MIN_VELAS_PARA_SCORE, len(data) - 1))
    if not indices_disponibles or cantidad == 0:
        return senales

    for _ in range(cantidad):
        i = random.choice(indices_disponibles)
        precio = float(data.iloc[i]["Close"])
        resultado, variacion, velas = _simular_resultado(data, i, precio)
        senales.append(ResultadoSenal(
            symbol=symbol, entrada_ts=data.index[i], entrada_precio=precio,
            score=0, resultado=resultado, variacion_pct=variacion,
            velas_hasta_resolver=velas,
        ))

    return senales


def _resumir(senales, titulo):
    print("=" * 90)
    print(titulo)
    print("=" * 90)

    n = len(senales)
    if n == 0:
        print("Sin señales.")
        print("=" * 90)
        return None

    ganaron = [s for s in senales if s.resultado == "GANO"]
    perdieron = [s for s in senales if s.resultado == "PERDIO"]
    sin_resolver = [s for s in senales if s.resultado == "SIN_RESOLVER"]

    resueltas = len(ganaron) + len(perdieron)
    win_rate = (len(ganaron) / resueltas * 100) if resueltas else 0.0
    variacion_promedio = sum(s.variacion_pct for s in senales) / n

    print(f"Total señales: {n}")
    print(f"Ganaron (+{OBJETIVO_INICIAL_PCT*100:.0f}%): {len(ganaron)} | "
          f"Perdieron (-{STOP_INICIAL_PCT*100:.0f}%): {len(perdieron)} | "
          f"Sin resolver: {len(sin_resolver)}")
    print(f"Win rate (sobre resueltas): {win_rate:.1f}%")
    print(f"Variación promedio de todas las señales: {variacion_promedio:+.2f}%")

    if n < 30:
        print()
        print("⚠️  Muestra menor a 30 - no es suficiente para conclusiones estadísticas firmes.")

    print("=" * 90)

    return {"n": n, "win_rate": win_rate, "variacion_promedio": variacion_promedio}


def _resumir_por_score(senales):
    print()
    print("DESGLOSE POR RANGO DE SCORE")
    print("-" * 90)

    for lo, hi in ((80, 85), (85, 90), (90, 95), (95, 101)):
        grupo = [s for s in senales if lo <= s.score < hi]
        if not grupo:
            continue
        ganaron = len([s for s in grupo if s.resultado == "GANO"])
        perdieron = len([s for s in grupo if s.resultado == "PERDIO"])
        resueltas = ganaron + perdieron
        win_rate = (ganaron / resueltas * 100) if resueltas else 0.0
        print(f"Score {lo}-{hi-1}: {len(grupo):3} señales | win rate {win_rate:5.1f}% ({ganaron}G/{perdieron}P)")

    print("-" * 90)


def correr_backtest(dias, activos):
    todas_reales = []
    todas_aleatorias = []
    omitidos = []

    for symbol in activos:
        print(f"Procesando {symbol}...")
        data = _cargar_datos(symbol, dias)

        if data is None or len(data) < MIN_VELAS_PARA_SCORE + 10:
            omitidos.append(symbol)
            continue

        senales_reales = _generar_senales_reales(symbol, data)
        todas_reales.extend(senales_reales)

        senales_random = _generar_senales_aleatorias(
            symbol, data, len(senales_reales), semilla=hash(symbol) % 10000
        )
        todas_aleatorias.extend(senales_random)

    print()
    resumen_real = _resumir(
        todas_reales,
        f"RESULTADOS: SEÑALES REALES DEL SISTEMA (score >= {Settings.UMBRAL_SENAL})",
    )
    if todas_reales:
        _resumir_por_score(todas_reales)

    print()
    resumen_random = _resumir(
        todas_aleatorias,
        "RESULTADOS: GRUPO DE CONTROL (entradas aleatorias, mismo stop/objetivo)",
    )

    print()
    print("=" * 90)
    print("CONCLUSIÓN")
    print("=" * 90)

    if resumen_real and resumen_random:
        diferencia = resumen_real["win_rate"] - resumen_random["win_rate"]
        print(f"Win rate del sistema:  {resumen_real['win_rate']:.1f}% (n={resumen_real['n']})")
        print(f"Win rate aleatorio:    {resumen_random['win_rate']:.1f}% (n={resumen_random['n']})")
        print(f"Diferencia: {diferencia:+.1f} puntos porcentuales")

        if resumen_real["n"] < 30 or resumen_random["n"] < 30:
            print()
            print("Con una muestra menor a 30 en cualquiera de los dos grupos, "
                  "esta diferencia NO es concluyente todavía.")
    else:
        print("No hay suficientes datos en ninguno de los dos grupos para comparar.")

    if omitidos:
        print()
        print(f"Activos omitidos por falta de datos ({len(omitidos)}): {', '.join(omitidos)}")

    print("=" * 90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dias", type=int, default=59,
        help="Días de histórico a analizar (máx ~60, límite de Yahoo Finance para velas de 5 min)",
    )
    parser.add_argument(
        "--activos", type=str, default=None,
        help="Lista de tickers separados por coma. Si no se especifica, usa todos los de Settings",
    )
    args = parser.parse_args()

    activos = args.activos.split(",") if args.activos else Settings.todos_los_activos()

    correr_backtest(args.dias, activos)