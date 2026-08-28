"""
Momentum de sección cruzada (cross-sectional momentum) - un enfoque
FUNDAMENTALMENTE DISTINTO a todo lo probado en esta sesión hasta ahora.

En vez de preguntar "¿esta acción específica va a subir, mirando su
propia historia?" (lo que hemos probado con RSI, MACD, drawdown, etc.),
aquí se pregunta: "de un grupo de acciones, ¿las que más subieron en los
últimos N meses (los 'ganadores' relativos) le ganan, en el mes
siguiente, a las que más cayeron (los 'perdedores' relativos)?"

Esta es la versión de "momentum" con el respaldo académico más fuerte y
replicado de toda la literatura de finanzas (Jegadeesh & Titman 1993, y
cientos de estudios posteriores en distintos mercados y períodos) - y es
genuinamente distinta a todo lo que probamos antes, porque compara
ACCIONES ENTRE SÍ cada mes, no una acción contra su propia historia.

Metodología:
  1. Cada mes, calcular el retorno de los últimos 3 meses de cada acción
     (el "período de formación").
  2. Ordenar las acciones de mejor a peor retorno.
  3. Formar un grupo "ganadores" (las mejores 3) y un grupo "perdedores"
     (las peores 3).
  4. Medir el retorno de CADA grupo en el mes SIGUIENTE (el período de
     prueba, sin ver el futuro - se decide con datos de ayer, se mide el
     resultado de mañana).
  5. Repetir mes a mes, y comparar el promedio de "ganadores" vs
     "perdedores" vs un grupo aleatorio, con la misma prueba de
     permutación usada en el resto de la sesión.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_momentum_seccion_cruzada.py
"""

import random
import sys
from pathlib import Path

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings

_CRIPTOS_A_EXCLUIR = {"BTC-USD", "ETH-USD", "SOL-USD"}
ACTIVOS = [a for a in Settings.todos_los_activos() if a not in _CRIPTOS_A_EXCLUIR]

FECHA_INICIO = "2018-01-01"  # se necesitan años, no meses, para tener suficientes períodos de prueba mensuales
UMBRAL_ANOMALIA = 15.0

MESES_FORMACION = 3   # cuántos meses hacia atrás mirar para definir "ganadores/perdedores"
TAMANO_GRUPO = 3       # cuántas acciones en el grupo "ganadores" y en "perdedores"

N_PERMUTACIONES = 2000


def _cargar_datos_diarios(symbol, fecha_inicio):
    try:
        data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    except Exception:
        return None
    if data.empty:
        return None
    return data


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    data = data[data["Volume"] > 0]
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _serie_mensual(data):
    """Convierte una serie diaria a un cierre por mes calendario (el
    último cierre disponible de cada mes)."""

    data = data.copy()
    data.index = data.index.tz_localize(None) if data.index.tz is not None else data.index
    data["periodo"] = data.index.to_period("M")
    cierres_mensuales = data.groupby("periodo")["Close"].last()
    return cierres_mensuales


def _prueba_permutacion_dos_grupos(valores_grupo1, valores_grupo2, n_permutaciones):
    v1 = np.array(valores_grupo1, dtype=float)
    v2 = np.array(valores_grupo2, dtype=float)

    diferencia_real = v1.mean() - v2.mean()

    todos = np.concatenate([v1, v2])
    n1 = len(v1)

    rng = np.random.default_rng(42)
    diferencias_azar = np.zeros(n_permutaciones)

    for k in range(n_permutaciones):
        mezclado = rng.permutation(todos)
        diferencias_azar[k] = mezclado[:n1].mean() - mezclado[n1:].mean()

    p_valor = float((np.abs(diferencias_azar) >= abs(diferencia_real)).mean())

    return diferencia_real, p_valor


def correr():
    print(f"Momentum de sección cruzada: {len(ACTIVOS)} activos, formación de {MESES_FORMACION} meses, "
          f"grupos de {TAMANO_GRUPO}")
    print()

    series_mensuales = {}

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, FECHA_INICIO)
        if data is None or len(data) < 40:
            continue
        data = _limpiar_datos(data)
        serie = _serie_mensual(data)
        if len(serie) >= MESES_FORMACION + 2:
            series_mensuales[symbol] = serie

    print(f"Activos con suficiente historia mensual: {len(series_mensuales)}")

    todos_los_periodos = sorted(set().union(*[set(s.index) for s in series_mensuales.values()]))
    print(f"Períodos (meses) disponibles: {[str(p) for p in todos_los_periodos]}")
    print()

    retornos_ganadores = []
    retornos_perdedores = []
    retornos_aleatorios = []

    for i in range(MESES_FORMACION, len(todos_los_periodos) - 1):
        periodo_formacion_inicio = todos_los_periodos[i - MESES_FORMACION]
        periodo_formacion_fin = todos_los_periodos[i]
        periodo_prueba = todos_los_periodos[i + 1]

        retornos_formacion = {}
        for symbol, serie in series_mensuales.items():
            if periodo_formacion_inicio in serie.index and periodo_formacion_fin in serie.index:
                precio_inicio = serie[periodo_formacion_inicio]
                precio_fin = serie[periodo_formacion_fin]
                retornos_formacion[symbol] = (precio_fin - precio_inicio) / precio_inicio * 100

        if len(retornos_formacion) < TAMANO_GRUPO * 2 + 2:
            continue

        ordenados = sorted(retornos_formacion.items(), key=lambda x: x[1], reverse=True)
        ganadores = [s for s, _ in ordenados[:TAMANO_GRUPO]]
        perdedores = [s for s, _ in ordenados[-TAMANO_GRUPO:]]

        retornos_prueba_mes = {}
        for symbol in retornos_formacion:
            serie = series_mensuales[symbol]
            if periodo_formacion_fin in serie.index and periodo_prueba in serie.index:
                precio_inicio = serie[periodo_formacion_fin]
                precio_fin = serie[periodo_prueba]
                retornos_prueba_mes[symbol] = (precio_fin - precio_inicio) / precio_inicio * 100

        r_ganadores = [retornos_prueba_mes[s] for s in ganadores if s in retornos_prueba_mes]
        r_perdedores = [retornos_prueba_mes[s] for s in perdedores if s in retornos_prueba_mes]

        if r_ganadores:
            retornos_ganadores.append(np.mean(r_ganadores))
        if r_perdedores:
            retornos_perdedores.append(np.mean(r_perdedores))

        random.seed(hash(str(periodo_prueba)) % 10000)
        simbolos_disponibles = list(retornos_prueba_mes.keys())
        if len(simbolos_disponibles) >= TAMANO_GRUPO:
            muestra_aleatoria = random.sample(simbolos_disponibles, TAMANO_GRUPO)
            r_aleatorio = [retornos_prueba_mes[s] for s in muestra_aleatoria]
            retornos_aleatorios.append(np.mean(r_aleatorio))

        print(f"  {periodo_prueba}: ganadores({','.join(ganadores)})={np.mean(r_ganadores):+.2f}% | "
              f"perdedores({','.join(perdedores)})={np.mean(r_perdedores):+.2f}%")

    print()
    print("=" * 100)
    print(f"RESUMEN ({len(retornos_ganadores)} meses de prueba)")
    print("=" * 100)
    print(f"Retorno promedio mensual - Ganadores (momentum alto):  {np.mean(retornos_ganadores):+.3f}%")
    print(f"Retorno promedio mensual - Perdedores (momentum bajo): {np.mean(retornos_perdedores):+.3f}%")
    print(f"Retorno promedio mensual - Grupo aleatorio:            {np.mean(retornos_aleatorios):+.3f}%")
    print()

    if len(retornos_ganadores) >= 5 and len(retornos_perdedores) >= 5:
        diferencia, p_valor = _prueba_permutacion_dos_grupos(retornos_ganadores, retornos_perdedores, N_PERMUTACIONES)
        print(f"Diferencia (ganadores - perdedores): {diferencia:+.3f} puntos porcentuales | p-valor: {p_valor:.4f}")

        if len(retornos_ganadores) < 20:
            print("⚠️  Muestra de meses todavía chica (menos de 20 meses de prueba) - "
                  "resultado indicativo, no concluyente.")
    else:
        print("Muestra insuficiente para la prueba estadística.")

    print("=" * 100)


if __name__ == "__main__":
    correr()