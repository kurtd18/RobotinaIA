"""
Time Series Momentum (TSMOM) - adaptación de la estrategia documentada
en Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", Journal of
Financial Economics, sobre nuestro universo de 60 activos (BVC +
internacional + ETF).

ADVERTENCIA HONESTA: el estudio original se hizo sobre 58 FUTUROS
LÍQUIDOS de índices, bonos, monedas y commodities - no acciones
individuales, muchas de ellas de baja liquidez como buena parte de
nuestro universo BVC. Esto es una adaptación, no una réplica exacta del
estudio - los resultados pueden diferir bastante del Sharpe ratio de
1.28 documentado en el paper original.

Señal: cada mes, para cada activo, se calcula su retorno de los últimos
12 meses. Si es positivo, se compra (posición larga) para el mes
siguiente. Si es negativo, se evita (no se opera - versión "long only",
más realista para un inversionista retail que no puede ir corto
fácilmente en la BVC).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_tsmom.py
"""

import sys
from pathlib import Path

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings

_CRIPTOS_A_EXCLUIR = {"BTC-USD", "ETH-USD", "SOL-USD"}
ACTIVOS = [a for a in Settings.todos_los_activos() if a not in _CRIPTOS_A_EXCLUIR]

FECHA_INICIO = "2022-01-01"
UMBRAL_ANOMALIA = 15.0

MESES_FORMACION = 12  # el "12M" del estudio original

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

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
    data = data.copy()
    data.index = data.index.tz_localize(None) if data.index.tz is not None else data.index
    data["periodo"] = data.index.to_period("M")
    return data.groupby("periodo")["Close"].last()


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


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
    print(f"Time Series Momentum: {len(ACTIVOS)} activos, formación de {MESES_FORMACION} meses")
    print("(ADVERTENCIA: adaptación a acciones individuales - el estudio original usó futuros líquidos)")
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

    print(f"Activos con suficiente historia: {len(series_mensuales)}")

    todos_los_periodos = sorted(set().union(*[set(s.index) for s in series_mensuales.values()]))
    print(f"Períodos disponibles: {len(todos_los_periodos)} meses")
    print()

    retornos_senal_positiva = []   # activo con momentum positivo (12M > 0) -> se compra
    retornos_senal_negativa = []   # activo con momentum negativo (12M <= 0) -> se hubiera evitado

    for i in range(MESES_FORMACION, len(todos_los_periodos) - 1):
        periodo_formacion_inicio = todos_los_periodos[i - MESES_FORMACION]
        periodo_formacion_fin = todos_los_periodos[i]
        periodo_prueba = todos_los_periodos[i + 1]

        for symbol, serie in series_mensuales.items():
            if periodo_formacion_inicio not in serie.index or periodo_formacion_fin not in serie.index:
                continue
            if periodo_prueba not in serie.index:
                continue

            precio_inicio_formacion = serie[periodo_formacion_inicio]
            precio_fin_formacion = serie[periodo_formacion_fin]
            momentum_12m = (precio_fin_formacion - precio_inicio_formacion) / precio_inicio_formacion * 100

            precio_fin_prueba = serie[periodo_prueba]
            retorno_mes_prueba = (precio_fin_prueba - precio_fin_formacion) / precio_fin_formacion * 100

            if momentum_12m > 0:
                retornos_senal_positiva.append(retorno_mes_prueba)
            else:
                retornos_senal_negativa.append(retorno_mes_prueba)

    print("=" * 100)
    print("RESULTADO")
    print("=" * 100)
    print(f"Casos con momentum de 12M POSITIVO (se compraría): {len(retornos_senal_positiva)}")
    print(f"  Retorno promedio del mes siguiente: {np.mean(retornos_senal_positiva):+.3f}%")
    print(f"  Neto simulado por operación: ${_calcular_dinero(np.mean(retornos_senal_positiva)):+,.0f} COP")
    print()
    print(f"Casos con momentum de 12M NEGATIVO (se evitaría): {len(retornos_senal_negativa)}")
    print(f"  Retorno promedio del mes siguiente: {np.mean(retornos_senal_negativa):+.3f}%")
    print()

    if len(retornos_senal_positiva) >= 30 and len(retornos_senal_negativa) >= 30:
        diferencia, p_valor = _prueba_permutacion_dos_grupos(
            retornos_senal_positiva, retornos_senal_negativa, N_PERMUTACIONES
        )
        print(f"Diferencia (momentum positivo - momentum negativo): {diferencia:+.3f} puntos porcentuales")
        print(f"p-valor: {p_valor:.4f}")
    else:
        print("Muestra insuficiente para la prueba estadística formal.")

    print("=" * 100)


if __name__ == "__main__":
    correr()