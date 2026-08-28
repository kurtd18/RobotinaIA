"""
VERSIÓN FINAL Y CONSOLIDADA del backtest de "drawdown -10% + trailing
stop", incorporando todo lo validado y corregido durante la
investigación de esta sesión:

  - Señal de entrada: el momento exacto en que el drawdown desde el
    máximo de 20 días CRUZA a -10% o más (no cada día que se mantiene
    ahí).
  - Salida: trailing stop real (stop inicial -5%, objetivo inicial +8%,
    incrementos de +1% - los parámetros que dieron el mejor resultado en
    las pruebas de sensibilidad).
  - Limpieza de datos: se excluyen filas con NaN (velas incompletas, ej.
    la más reciente si el mercado sigue abierto) y velas "fantasma" con
    volumen cero (festivos que Yahoo Finance rellena con un valor plano
    en vez de omitir).
  - Por cada operación: además del resultado en dinero, se registra
    cuántos días tardó en cruzar a terreno positivo por primera vez, y
    cuántos días duró en total hasta la salida real - para entender el
    comportamiento temporal real de la estrategia, no solo el resultado
    final.
  - Calibración/validación fuera de muestra (primera mitad vs segunda
    mitad cronológica de cada activo).
  - Grupo de control aleatorio del mismo tamaño, para saber si la señal
    de verdad le gana al azar.

IMPORTANTE - lo que ya sabemos de esta señal (no repetir el mismo error
de confiar ciegamente en un resultado positivo):
  - Se sostiene con muestra grande (1000+ operaciones) en 63 activos de
    mercados distintos, en la ventana 2018-2026.
  - La ventaja sobre el azar se reduce mientras más reciente es la
    ventana de tiempo (fuerte en 2018-2026, moderada en 2024-2026, casi
    nula en 2025-2026) - sugiere que la ventaja depende de eventos de
    caída severa poco frecuentes (ej. COVID 2020), no de un efecto
    constante y operable semana a semana.
  - Varias señales dentro de un mismo país/mercado están correlacionadas
    entre sí (una corrección afecta a muchas acciones a la vez), así que
    el N real de eventos independientes es menor al N de operaciones.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_drawdown_final.py
    python scripts/backtest_drawdown_final.py --activos ECOPETROL.CL,GEB.CL --inicio 2024-01-01
    python scripts/backtest_drawdown_final.py --todos_63 --inicio 2018-01-01
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS_BVC_10 = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

UMBRAL_ANOMALIA = 15.0
VENTANA_MAXIMO = 20
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

MIN_MUESTRA_CONFIABLE = 30


def _cargar_datos_diarios(symbol, fecha_inicio):
    try:
        data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    except Exception:
        return None
    if data.empty:
        return None
    return data


def _limpiar_datos(data):
    # Quitar filas con datos faltantes (velas incompletas)
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    # Quitar velas fantasma: volumen cero (festivos que Yahoo Finance
    # rellena con un valor plano en vez de omitir por completo)
    data = data[data["Volume"] > 0]
    # Quitar movimientos absurdos de un solo día (probable split de
    # acciones mal ajustado, no un movimiento real del mercado)
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_drawdown(data, ventana_maximo, umbral_drawdown):
    """Devuelve los índices donde el drawdown desde el máximo de
    `ventana_maximo` días CRUZA a `umbral_drawdown`% o más (el momento
    exacto, no cada día que se mantiene ahí)."""

    maximo_reciente = data["Close"].rolling(ventana_maximo).max().shift(1)
    drawdown_pct = -((data["Close"] - maximo_reciente) / maximo_reciente * 100)

    cruces = []
    for i in range(ventana_maximo + 1, len(data)):
        dd_hoy = drawdown_pct.iloc[i]
        dd_ayer = drawdown_pct.iloc[i - 1]

        if dd_hoy != dd_hoy or dd_ayer != dd_ayer:
            continue

        if dd_ayer < umbral_drawdown and dd_hoy >= umbral_drawdown:
            cruces.append(i)

    return cruces


def _simular_trailing_stop_con_tiempos(data, idx_entrada, entrada_precio, stop_inicial_pct, objetivo_inicial_pct):
    """Simula el trailing stop y además registra cuántos días tardó en
    cruzar a terreno positivo por primera vez (precio > entrada), además
    de cuándo y a qué precio salió."""

    stop = entrada_precio * (1 - stop_inicial_pct)
    objetivo = entrada_precio * (1 + objetivo_inicial_pct)

    n = len(data)
    dias_hasta_positivo = None

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]
        close = data["Close"].iloc[i]

        if dias_hasta_positivo is None and close > entrada_precio:
            dias_hasta_positivo = i - idx_entrada

        if low <= stop:
            return float(stop), data.index[i], i - idx_entrada, dias_hasta_positivo

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + INCREMENTO_PCT)

    precio_final = float(data["Close"].iloc[-1])
    return precio_final, data.index[-1], n - 1 - idx_entrada, dias_hasta_positivo


@dataclass
class Operacion:
    symbol: str
    entrada_fecha: object
    entrada_precio: float
    salida_fecha: object
    salida_precio: float
    dias_hasta_positivo: object  # None si nunca cruzó a positivo
    dias_hasta_salida: int
    variacion_pct: float
    neto: float
    resultado: str


def _simular_operaciones(symbol, data, indices_entrada, stop_inicial_pct, objetivo_inicial_pct):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        salida_precio, salida_fecha, dias_hasta_salida, dias_hasta_positivo = _simular_trailing_stop_con_tiempos(
            data, idx_entrada, entrada_precio, stop_inicial_pct, objetivo_inicial_pct
        )

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)
        resultado = "GANO" if neto > 0 else "PERDIO"

        operaciones.append(Operacion(
            symbol=symbol, entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            salida_fecha=salida_fecha, salida_precio=salida_precio,
            dias_hasta_positivo=dias_hasta_positivo, dias_hasta_salida=dias_hasta_salida,
            variacion_pct=variacion_pct, neto=neto, resultado=resultado,
        ))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(symbol, data, cantidad, semilla, minimo_idx, stop_inicial_pct, objetivo_inicial_pct):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(symbol, data, sorted(set(indices_random)), stop_inicial_pct, objetivo_inicial_pct)


def _resumen_tiempos(operaciones, titulo):
    if not operaciones:
        print(f"{titulo}: sin operaciones")
        return

    dias_positivo_validos = [op.dias_hasta_positivo for op in operaciones if op.dias_hasta_positivo is not None]
    nunca_positivo = sum(1 for op in operaciones if op.dias_hasta_positivo is None)

    ganadoras = [op for op in operaciones if op.resultado == "GANO"]
    perdedoras = [op for op in operaciones if op.resultado == "PERDIO"]

    print(f"--- Tiempos ({titulo}) ---")
    if dias_positivo_validos:
        print(f"  Días promedio hasta cruzar a positivo: {sum(dias_positivo_validos)/len(dias_positivo_validos):.1f} "
              f"(mínimo {min(dias_positivo_validos)}, máximo {max(dias_positivo_validos)})")
    print(f"  Nunca cruzaron a positivo: {nunca_positivo}/{len(operaciones)}")
    if ganadoras:
        dias_g = [op.dias_hasta_salida for op in ganadoras]
        print(f"  Días promedio hasta la venta (ganadoras): {sum(dias_g)/len(dias_g):.1f}")
    if perdedoras:
        dias_p = [op.dias_hasta_salida for op in perdedoras]
        print(f"  Días promedio hasta la venta (perdedoras): {sum(dias_p)/len(dias_p):.1f}")


def correr(activos, fecha_inicio, umbral_drawdown, stop_inicial_pct, objetivo_inicial_pct, mostrar_detalle):
    print(f"Activos: {len(activos)}")
    print(f"Señal: cruce de drawdown a -{umbral_drawdown:.0f}% o más desde el máximo de {VENTANA_MAXIMO} días")
    print(f"Salida: trailing stop (-{stop_inicial_pct*100:.1f}%/+{objetivo_inicial_pct*100:.1f}%/"
          f"+{INCREMENTO_PCT*100:.0f}%)")
    print(f"Desembolso: ${DESEMBOLSO_TOTAL:,.0f} COP | Comisión: ${COMISION:,.0f} COP/lado")
    print()

    todas_calib = []
    todas_valid = []
    todas_operaciones = []
    datos_por_symbol = {}

    for symbol in activos:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < VENTANA_MAXIMO + 20:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _limpiar_datos(data)
        if len(data) < VENTANA_MAXIMO + 20:
            print(f"{symbol}: sin datos suficientes tras la limpieza")
            continue

        datos_por_symbol[symbol] = data

        cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, umbral_drawdown)
        operaciones = _simular_operaciones(symbol, data, cruces, stop_inicial_pct, objetivo_inicial_pct)

        if not operaciones:
            continue

        if mostrar_detalle:
            print(f"=== {symbol} ===")
            for op in operaciones:
                dias_pos_str = f"{op.dias_hasta_positivo} días" if op.dias_hasta_positivo is not None else "nunca"
                print(f"  {op.entrada_fecha.strftime('%Y-%m-%d')} @ ${op.entrada_precio:,.2f} -> "
                      f"{op.salida_fecha.strftime('%Y-%m-%d')} @ ${op.salida_precio:,.2f} | "
                      f"cruzó a positivo en: {dias_pos_str} | duró: {op.dias_hasta_salida} días | "
                      f"{op.resultado} ({op.variacion_pct:+.2f}%) | neto {op.neto:+,.0f} COP")

        punto_medio = len(operaciones) // 2
        calib = operaciones[:punto_medio]
        valid = operaciones[punto_medio:]

        neto_symbol = sum(op.neto for op in operaciones)
        print(f"{symbol:14} {len(operaciones):3} operaciones | neto ${neto_symbol:+,.0f} COP "
              f"(calib={len(calib)}, valid={len(valid)})")

        todas_calib.extend(calib)
        todas_valid.extend(valid)
        todas_operaciones.extend(operaciones)

    print()
    print("=" * 100)
    print(f"CALIBRACIÓN: {len(todas_calib)} operaciones")
    print("=" * 100)
    if todas_calib:
        neto_calib = sum(op.neto for op in todas_calib)
        ganaron_calib = sum(1 for op in todas_calib if op.neto > 0)
        print(f"Neto total: ${neto_calib:+,.0f} COP | Ganadoras: {ganaron_calib}/{len(todas_calib)} "
              f"({ganaron_calib/len(todas_calib)*100:.1f}%)")

    print()
    print("=" * 100)
    print(f"VALIDACIÓN FUERA DE MUESTRA: {len(todas_valid)} operaciones")
    print("=" * 100)

    if todas_valid:
        neto_valid = sum(op.neto for op in todas_valid)
        ganaron_valid = sum(1 for op in todas_valid if op.neto > 0)
        print(f"Neto total: ${neto_valid:+,.0f} COP | Ganadoras: {ganaron_valid}/{len(todas_valid)} "
              f"({ganaron_valid/len(todas_valid)*100:.1f}%)")

        n_total = 0
        neto_random_total = 0.0
        for symbol, data in datos_por_symbol.items():
            cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, umbral_drawdown)
            operaciones = _simular_operaciones(symbol, data, cruces, stop_inicial_pct, objetivo_inicial_pct)
            punto_medio = len(operaciones) // 2
            n_valid_symbol = len(operaciones) - punto_medio

            aleatorias = _generar_aleatorias(
                symbol, data, n_valid_symbol, hash(symbol) % 10000, VENTANA_MAXIMO,
                stop_inicial_pct, objetivo_inicial_pct
            )
            neto_random_total += sum(op.neto for op in aleatorias)
            n_total += len(aleatorias)

        print(f"Grupo de control aleatorio (mismo tamaño): {n_total} operaciones | "
              f"neto ${neto_random_total:+,.0f} COP")

        if len(todas_valid) < MIN_MUESTRA_CONFIABLE:
            print(f"⚠️  Muestra menor a {MIN_MUESTRA_CONFIABLE} - resultado indicativo, no concluyente todavía.")
    else:
        print("Sin operaciones en validación.")

    print()
    print("=" * 100)
    print("COMPORTAMIENTO TEMPORAL (todas las operaciones, calibración + validación)")
    print("=" * 100)
    _resumen_tiempos(todas_operaciones, "todas las operaciones")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activos", type=str, default=None,
                        help="Lista separada por comas. Por defecto usa las 10 acciones BVC.")
    parser.add_argument("--todos_63", action="store_true",
                        help="Usar el universo completo de 63 activos (requiere app.core.settings.Settings)")
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--umbral_drawdown", type=float, default=10.0)
    parser.add_argument("--stop", type=float, default=0.05)
    parser.add_argument("--objetivo", type=float, default=0.08)
    parser.add_argument("--sin_detalle", action="store_true", help="No imprimir el detalle de cada operación")
    args = parser.parse_args()

    if args.todos_63:
        from app.core.settings import Settings
        activos = Settings.todos_los_activos()
    elif args.activos:
        activos = args.activos.split(",")
    else:
        activos = ACTIVOS_BVC_10

    correr(activos, args.inicio, args.umbral_drawdown, args.stop, args.objetivo, not args.sin_detalle)