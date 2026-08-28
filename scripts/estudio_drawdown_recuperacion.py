"""
Estudio estadístico de la relación entre drawdown (qué tan lejos está el
precio de su máximo reciente) y el retorno futuro a distintos plazos -
sobre las 10 acciones BVC juntas, usando TODOS los días (no solo los
días donde se dispara una señal específica) para maximizar la muestra.

No es una prueba de una regla de trading con objetivo/stop fijo - es una
caracterización estadística pura: ¿existe una relación real y medible
entre "qué tan caro cayó el precio" y "cuánto/qué tan rápido se
recupera"? Si existe, debería verse tanto en los promedios agrupados por
nivel de drawdown, como en el coeficiente de correlación.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/estudio_drawdown_recuperacion.py
    python scripts/estudio_drawdown_recuperacion.py --ventana_maximo 20
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

UMBRAL_ANOMALIA = 15.0
VENTANA_VOLUMEN = 20
HORIZONTES = [5, 10, 20]

BINS_DRAWDOWN = [
    (0, 2, "0% a -2%"),
    (2, 5, "-2% a -5%"),
    (5, 10, "-5% a -10%"),
    (10, 100, "-10% o más"),
]


def _cargar_datos_diarios(symbol, fecha_inicio):
    data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_puntos(data, ventana_maximo):
    """Para cada día, calcula el drawdown respecto al máximo de los
    `ventana_maximo` días anteriores, el volumen relativo, y el retorno
    futuro a cada uno de los horizontes definidos."""

    maximo_reciente = data["Close"].rolling(ventana_maximo).max().shift(1)
    drawdown_pct = (data["Close"] - maximo_reciente) / maximo_reciente * 100

    volumen_promedio = data["Volume"].rolling(VENTANA_VOLUMEN).mean().shift(1)

    puntos = []
    n = len(data)

    for i in range(ventana_maximo, n):
        dd = drawdown_pct.iloc[i]
        if dd != dd or dd >= 0:  # NaN o sin caída real (dd negativo = caída)
            continue

        precio_hoy = float(data["Close"].iloc[i])

        vol_prom = volumen_promedio.iloc[i]
        vol_relativo = (
            float(data["Volume"].iloc[i]) / vol_prom
            if vol_prom == vol_prom and vol_prom > 0 else None
        )

        retornos = {}
        for h in HORIZONTES:
            if i + h < n:
                precio_futuro = float(data["Close"].iloc[i + h])
                retornos[h] = ((precio_futuro - precio_hoy) / precio_hoy) * 100

        puntos.append({
            "drawdown_pct": -dd,  # lo volvemos positivo para que sea más intuitivo (0 a 100)
            "vol_relativo": vol_relativo,
            "retornos": retornos,
        })

    return puntos


def _correlacion(xs, ys):
    """Coeficiente de correlación de Pearson entre dos listas."""

    pares = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pares) < 2:
        return None

    xs_v = np.array([p[0] for p in pares])
    ys_v = np.array([p[1] for p in pares])

    if xs_v.std() == 0 or ys_v.std() == 0:
        return None

    return float(np.corrcoef(xs_v, ys_v)[0, 1])


def _simular_caminata_aleatoria(n_dias, volatilidad_diaria_pct, semilla, precio_inicial=100.0):
    """Simula una caminata aleatoria SIN ninguna reversión real, con una
    volatilidad diaria comparable a la de un activo real, usando un
    generador de números aleatorios independiente."""

    rng = np.random.default_rng(semilla)
    retornos_diarios = rng.normal(0, volatilidad_diaria_pct / 100, n_dias)
    precios = precio_inicial * np.cumprod(1 + retornos_diarios)

    idx = pd.bdate_range("2020-01-01", periods=n_dias)
    data = pd.DataFrame({
        "Open": precios, "High": precios * 1.005, "Low": precios * 0.995,
        "Close": precios, "Volume": np.full(n_dias, 1000.0),
    }, index=idx)

    return data


def _control_montecarlo(volatilidad_diaria_pct, n_dias_por_serie, n_series, ventana_maximo, n_simulaciones=100):
    """Genera la distribución de correlaciones que produce el AZAR PURO
    con esta misma forma de medir (drawdown vs retorno futuro), simulando
    muchas caminatas aleatorias INDEPENDIENTES (no mezclando los datos
    reales, que no elimina el sesgo de ventanas superpuestas) - este es
    el control estadístico correcto para este problema específico."""

    correlaciones_por_horizonte = {h: [] for h in HORIZONTES}

    for sim in range(n_simulaciones):
        puntos_sim = []
        for serie_i in range(n_series):
            data_sim = _simular_caminata_aleatoria(
                n_dias_por_serie, volatilidad_diaria_pct, semilla=sim * 1000 + serie_i
            )
            puntos_sim.extend(_calcular_puntos(data_sim, ventana_maximo))

        drawdowns_sim = [p["drawdown_pct"] for p in puntos_sim]

        for h in HORIZONTES:
            retornos_sim = [p["retornos"].get(h) for p in puntos_sim]
            c = _correlacion(drawdowns_sim, retornos_sim)
            if c is not None:
                correlaciones_por_horizonte[h].append(c)

    return correlaciones_por_horizonte


def correr(fecha_inicio, ventana_maximo):
    todos_los_puntos = []
    datos_por_symbol = {}
    retornos_diarios_todos = []

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < ventana_maximo + max(HORIZONTES) + 10:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _filtrar_anomalias(data)
        datos_por_symbol[symbol] = data

        puntos = _calcular_puntos(data, ventana_maximo)
        todos_los_puntos.extend(puntos)

        retornos_diarios = (
            (data["Close"] - data["Close"].shift(1)) / data["Close"].shift(1) * 100
        ).dropna().tolist()
        retornos_diarios_todos.extend(retornos_diarios)

    print(f"Total de días con caída medible: {len(todos_los_puntos)} (sobre {len(ACTIVOS)} acciones)")
    print()

    print("=" * 100)
    print("RETORNO PROMEDIO FUTURO, AGRUPADO POR NIVEL DE DRAWDOWN")
    print("=" * 100)
    print(f"{'DRAWDOWN':16} {'N':>6}", end="")
    for h in HORIZONTES:
        print(f" {'Retorno ' + str(h) + 'd':>16}", end="")
    print()
    print("-" * 100)

    for lo, hi, etiqueta in BINS_DRAWDOWN:
        grupo = [p for p in todos_los_puntos if lo <= p["drawdown_pct"] < hi]

        print(f"{etiqueta:16} {len(grupo):>6}", end="")
        for h in HORIZONTES:
            valores = [p["retornos"][h] for p in grupo if h in p["retornos"]]
            promedio = sum(valores) / len(valores) if valores else None
            texto = f"{promedio:+.2f}%" if promedio is not None else "N/A"
            print(f" {texto:>16}", end="")
        print()

    print("-" * 100)
    print()

    print("=" * 100)
    print("CORRELACIÓN REAL vs. CONTROL DE MONTE CARLO (caminatas aleatorias independientes)")
    print("=" * 100)
    print("El control simula 100 conjuntos de 10 caminatas aleatorias SIN reversión real,")
    print("con volatilidad similar a los datos reales, y mide qué correlación produce el")
    print("puro azar con esta misma forma de medir - esto es lo que hay que superar para")
    print("decir que hay una señal real, no solo el artefacto de medir sobre ventanas.")
    print()

    drawdowns_reales = [p["drawdown_pct"] for p in todos_los_puntos]
    volatilidad_estim = float(np.std(retornos_diarios_todos))
    n_dias_promedio = int(np.mean([len(d) for d in datos_por_symbol.values()]))

    print(f"Volatilidad diaria estimada de los datos reales: {volatilidad_estim:.3f}%")
    print("Simulando controles de Monte Carlo (puede tardar un momento)...")
    print()

    control = _control_montecarlo(
        volatilidad_estim, n_dias_promedio, len(ACTIVOS), ventana_maximo, n_simulaciones=100
    )

    for h in HORIZONTES:
        retornos_h = [p["retornos"].get(h) for p in todos_los_puntos]
        corr_real = _correlacion(drawdowns_reales, retornos_h)

        corr_control = control[h]
        if corr_real is None or not corr_control:
            print(f"  Retorno a {h} días: datos insuficientes")
            continue

        control_arr = np.array(corr_control)
        percentil = float((control_arr <= corr_real).mean() * 100)

        print(f"  Retorno a {h} días:")
        print(f"    Correlación real:            {corr_real:+.4f}")
        print(f"    Control Monte Carlo (rango): {control_arr.min():+.4f} a {control_arr.max():+.4f} "
              f"(promedio {control_arr.mean():+.4f})")
        print(f"    La correlación real está en el percentil {percentil:.0f} del control de azar puro")

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--ventana_maximo", type=int, default=20)
    args = parser.parse_args()

    correr(args.inicio, args.ventana_maximo)