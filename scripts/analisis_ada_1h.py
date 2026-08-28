"""
Análisis detallado de ADAUSDT con velas de 1 hora, desde enero de 2026
hasta hoy, para determinar con evidencia (no copiando los porcentajes
usados en otras escalas de tiempo) qué umbral de drawdown y qué
parámetros de trailing stop tienen sentido a esta granularidad.

Mide:
  1. Volatilidad real hora a hora (para saber qué tamaño de movimiento es
     "normal" a esta escala, antes de fijar cualquier porcentaje).
  2. La relación entre "qué tan lejos cayó el precio" (drawdown desde el
     máximo de 20 horas) y el retorno futuro a distintos horizontes (6h,
     12h, 24h) - usando bins de tamaño apropiado para esta escala (no los
     mismos 0-2%/2-5%/5-10%/10%+ que usamos para datos diarios, que acá
     casi nunca se alcanzarían).
  3. Recomendación final de parámetros, basada en los resultados.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_ada_1h.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

SYMBOL = "ADAUSDT"
FECHA_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)
VENTANA_MAXIMO = 20  # horas
HORIZONTES = [6, 12, 24]  # horas hacia adelante


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    return data[data["Volume"] > 0]


def _calcular_puntos(data, ventana_maximo):
    maximo_reciente = data["Close"].rolling(ventana_maximo).max().shift(1)
    drawdown_pct = -((data["Close"] - maximo_reciente) / maximo_reciente * 100)
    # En esta convención, drawdown_pct > 0 significa que SÍ hubo una caída
    # real (el precio está por debajo del máximo reciente) - valores <= 0
    # significan que el precio está en o por encima de su máximo reciente
    # (sin caída, posible nuevo máximo).

    puntos = []
    n = len(data)

    for i in range(ventana_maximo, n):
        dd = drawdown_pct.iloc[i]
        if dd != dd or dd <= 0:
            continue  # sin caída real, o dato faltante - se descarta

        precio_hoy = float(data["Close"].iloc[i])
        retornos = {}
        for h in HORIZONTES:
            if i + h < n:
                precio_futuro = float(data["Close"].iloc[i + h])
                retornos[h] = ((precio_futuro - precio_hoy) / precio_hoy) * 100

        puntos.append({"drawdown_pct": dd, "retornos": retornos})

    return puntos


def correr():
    print(f"Descargando {SYMBOL}, velas de 1 hora, desde {FECHA_INICIO.strftime('%Y-%m-%d')}...")
    data = obtener_klines(SYMBOL, "1h", FECHA_INICIO)

    if data is None or len(data) < VENTANA_MAXIMO + 30:
        print("Sin datos suficientes.")
        return

    data = _limpiar_datos(data)
    print(f"Datos: {data.index[0].strftime('%Y-%m-%d %H:%M')} a {data.index[-1].strftime('%Y-%m-%d %H:%M')} "
          f"({len(data)} velas de 1h)")
    print()

    # --- Paso 1: volatilidad real hora a hora ---
    retornos_horarios = ((data["Close"] - data["Close"].shift(1)) / data["Close"].shift(1) * 100).dropna()

    print("=" * 100)
    print("VOLATILIDAD REAL HORA A HORA")
    print("=" * 100)
    print(f"Retorno horario promedio: {retornos_horarios.mean():+.4f}%")
    print(f"Desviación estándar horaria (volatilidad típica): {retornos_horarios.std():.4f}%")
    print(f"Movimiento horario más grande (positivo): {retornos_horarios.max():+.2f}%")
    print(f"Movimiento horario más grande (negativo): {retornos_horarios.min():+.2f}%")
    print(f"Percentil 95 (valor absoluto): {retornos_horarios.abs().quantile(0.95):.2f}%")
    print(f"Percentil 99 (valor absoluto): {retornos_horarios.abs().quantile(0.99):.2f}%")
    print()

    # --- Paso 2: drawdown desde el máximo de 20 horas - distribución ---
    maximo_reciente = data["Close"].rolling(VENTANA_MAXIMO).max().shift(1)
    drawdown_pct = -((data["Close"] - maximo_reciente) / maximo_reciente * 100)
    drawdown_valido = drawdown_pct.dropna()
    drawdown_caidas = drawdown_valido[drawdown_valido > 0]

    print("=" * 100)
    print(f"DISTRIBUCIÓN DEL DRAWDOWN (desde el máximo de {VENTANA_MAXIMO} horas, solo días de caída)")
    print("=" * 100)
    print(f"Drawdown promedio cuando hay caída: {drawdown_caidas.mean():.2f}%")
    print(f"Percentil 75: {drawdown_caidas.quantile(0.75):.2f}%")
    print(f"Percentil 90: {drawdown_caidas.quantile(0.90):.2f}%")
    print(f"Percentil 95: {drawdown_caidas.quantile(0.95):.2f}%")
    print(f"Máximo drawdown visto: {drawdown_caidas.max():.2f}%")
    print()

    # --- Paso 3: retorno futuro agrupado por nivel de drawdown (bins adaptados a esta escala) ---
    puntos = _calcular_puntos(data, VENTANA_MAXIMO)

    # Bins basados en los percentiles reales de ESTE activo, no copiados de otra escala
    p50 = float(drawdown_caidas.quantile(0.50))
    p75 = float(drawdown_caidas.quantile(0.75))
    p90 = float(drawdown_caidas.quantile(0.90))

    bins = [
        (0, p50, f"0% a {p50:.1f}% (mitad más baja)"),
        (p50, p75, f"{p50:.1f}% a {p75:.1f}%"),
        (p75, p90, f"{p75:.1f}% a {p90:.1f}%"),
        (p90, 100, f"{p90:.1f}% o más (el 10% de caídas más fuertes)"),
    ]

    print("=" * 100)
    print("RETORNO FUTURO PROMEDIO, AGRUPADO POR NIVEL DE DRAWDOWN (bins propios de ADA)")
    print("=" * 100)
    print(f"{'DRAWDOWN':40} {'N':>6}", end="")
    for h in HORIZONTES:
        print(f" {'Retorno ' + str(h) + 'h':>14}", end="")
    print()
    print("-" * 100)

    for lo, hi, etiqueta in bins:
        grupo = [p for p in puntos if lo <= p["drawdown_pct"] < hi]
        print(f"{etiqueta:40} {len(grupo):>6}", end="")
        for h in HORIZONTES:
            valores = [p["retornos"][h] for p in grupo if h in p["retornos"]]
            promedio = sum(valores) / len(valores) if valores else None
            texto = f"{promedio:+.3f}%" if promedio is not None else "N/A"
            print(f" {texto:>14}", end="")
        print()

    print("-" * 100)
    print()

    # --- Paso 4: recomendación de parámetros ---
    print("=" * 100)
    print("RECOMENDACIÓN DE PARÁMETROS PARA ADAUSDT A 1 HORA (basada en lo medido arriba)")
    print("=" * 100)
    print(f"Umbral de drawdown sugerido: {p75:.1f}% a {p90:.1f}% "
          f"(percentil 75-90 de las caídas reales de ADA a esta escala)")
    print(f"Stop inicial sugerido: {retornos_horarios.abs().quantile(0.95):.2f}% "
          f"(cercano al percentil 95 del movimiento horario típico - un stop más ajustado "
          f"se activaría por ruido normal, no por una reversión real)")
    print(f"Objetivo inicial sugerido: {p50:.1f}% a {p75:.1f}% "
          f"(un rebote de esa magnitud sería consistente con la mitad/tres cuartos de las caídas típicas)")
    print()
    print("Estos son puntos de partida sugeridos por los datos - falta correr el backtest de dinero")
    print("real con estos valores y validar fuera de muestra antes de confiar en ellos.")
    print("=" * 100)


if __name__ == "__main__":
    correr()