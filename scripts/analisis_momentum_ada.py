"""
Estudio de momentum/continuación para ADAUSDT: mide la relación entre
"qué tan lejos subió el precio desde su mínimo reciente" (run-up) y el
retorno futuro - la imagen espejo del estudio de drawdown, para probar
si las subidas fuertes tienden a seguir subiendo (momentum) en vez de
revertir.

Se corre en dos escalas: velas de 1 hora y de 4 horas, para 2026.

Incluye el mismo control de Monte Carlo que usamos en el estudio de
drawdown de BVC - comparar contra caminatas aleatorias independientes,
no solo contra cero, porque medir sobre ventanas móviles puede producir
una correlación aparente incluso en datos sin ninguna relación real.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_momentum_ada.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

SYMBOL = "ADAUSDT"
FECHA_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)
VENTANA_MINIMO = 20  # velas


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    return data[data["Volume"] > 0]


def _calcular_puntos_runup(data, ventana_minimo, horizontes):
    """Calcula, para cada vela, qué tan lejos subió el precio desde el
    mínimo de las `ventana_minimo` velas anteriores (run-up, la imagen
    espejo del drawdown), y el retorno futuro a cada horizonte."""

    minimo_reciente = data["Close"].rolling(ventana_minimo).min().shift(1)
    runup_pct = (data["Close"] - minimo_reciente) / minimo_reciente * 100

    puntos = []
    n = len(data)

    for i in range(ventana_minimo, n):
        ru = runup_pct.iloc[i]
        if ru != ru or ru <= 0:
            continue  # sin subida real, o dato faltante

        precio_hoy = float(data["Close"].iloc[i])
        retornos = {}
        for h in horizontes:
            if i + h < n:
                precio_futuro = float(data["Close"].iloc[i + h])
                retornos[h] = ((precio_futuro - precio_hoy) / precio_hoy) * 100

        puntos.append({"runup_pct": ru, "retornos": retornos})

    return puntos


def _correlacion(xs, ys):
    pares = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pares) < 2:
        return None
    xs_v = np.array([p[0] for p in pares])
    ys_v = np.array([p[1] for p in pares])
    if xs_v.std() == 0 or ys_v.std() == 0:
        return None
    return float(np.corrcoef(xs_v, ys_v)[0, 1])


def _simular_caminata_aleatoria(n_velas, volatilidad_pct, semilla, precio_inicial=100.0):
    rng = np.random.default_rng(semilla)
    retornos = rng.normal(0, volatilidad_pct / 100, n_velas)
    precios = precio_inicial * np.cumprod(1 + retornos)
    idx = pd.date_range("2020-01-01", periods=n_velas, freq="h")
    return pd.DataFrame({
        "Open": precios, "High": precios * 1.002, "Low": precios * 0.998,
        "Close": precios, "Volume": np.full(n_velas, 1000.0),
    }, index=idx)


def _control_montecarlo(volatilidad_pct, n_velas, ventana_minimo, horizontes, n_simulaciones):
    correlaciones_por_horizonte = {h: [] for h in horizontes}

    for sim in range(n_simulaciones):
        data_sim = _simular_caminata_aleatoria(n_velas, volatilidad_pct, semilla=sim)
        puntos_sim = _calcular_puntos_runup(data_sim, ventana_minimo, horizontes)

        runups_sim = [p["runup_pct"] for p in puntos_sim]

        for h in horizontes:
            retornos_sim = [p["retornos"].get(h) for p in puntos_sim]
            c = _correlacion(runups_sim, retornos_sim)
            if c is not None:
                correlaciones_por_horizonte[h].append(c)

    return correlaciones_por_horizonte


def analizar_intervalo(interval, horizontes, etiquetas_horizonte, n_simulaciones=60):
    print("=" * 100)
    print(f"MOMENTUM/CONTINUACIÓN - {SYMBOL} - VELAS DE {interval.upper()}")
    print("=" * 100)

    data = obtener_klines(SYMBOL, interval, FECHA_INICIO)
    if data is None or len(data) < VENTANA_MINIMO + max(horizontes) + 30:
        print("Sin datos suficientes.")
        return

    data = _limpiar_datos(data)
    print(f"Datos: {data.index[0].strftime('%Y-%m-%d %H:%M')} a {data.index[-1].strftime('%Y-%m-%d %H:%M')} "
          f"({len(data)} velas)")

    retornos_periodo = ((data["Close"] - data["Close"].shift(1)) / data["Close"].shift(1) * 100).dropna()
    volatilidad = float(retornos_periodo.std())
    print(f"Volatilidad por vela: {volatilidad:.3f}%")
    print()

    puntos = _calcular_puntos_runup(data, VENTANA_MINIMO, horizontes)
    print(f"Velas con subida medible: {len(puntos)}")
    print()

    runups = [p["runup_pct"] for p in puntos]

    print(f"{'HORIZONTE':12} {'Correlación real':>18} {'Control Monte Carlo':>28} {'Percentil':>12}")
    print("-" * 100)

    control = _control_montecarlo(volatilidad, len(data), VENTANA_MINIMO, horizontes, n_simulaciones)

    for h, etiqueta in zip(horizontes, etiquetas_horizonte):
        retornos_h = [p["retornos"].get(h) for p in puntos]
        corr_real = _correlacion(runups, retornos_h)

        corr_control = control[h]
        if corr_real is None or not corr_control:
            print(f"{etiqueta:12} datos insuficientes")
            continue

        control_arr = np.array(corr_control)
        percentil = float((control_arr <= corr_real).mean() * 100)

        rango_str = f"{control_arr.min():+.3f} a {control_arr.max():+.3f}"
        print(f"{etiqueta:12} {corr_real:>+18.4f} {rango_str:>28} {percentil:>11.0f}")

    print()


if __name__ == "__main__":
    print(f"Estudio de momentum/continuación para {SYMBOL}, desde {FECHA_INICIO.strftime('%Y-%m-%d')}")
    print()

    analizar_intervalo("1h", horizontes=[6, 12, 24], etiquetas_horizonte=["6h", "12h", "24h"])
    analizar_intervalo("4h", horizontes=[6, 12, 24], etiquetas_horizonte=["24h", "48h", "96h"])

    # A estas escalas hay muchas más velas (5m en 7 meses son ~61,000) -
    # se reduce el número de simulaciones de control para que no tarde
    # demasiado, sin perder el rigor del control estadístico.
    analizar_intervalo("15m", horizontes=[4, 8, 16], etiquetas_horizonte=["1h", "2h", "4h"], n_simulaciones=25)
    analizar_intervalo("5m", horizontes=[6, 12, 24], etiquetas_horizonte=["30min", "1h", "2h"], n_simulaciones=15)