"""
Análisis sistemático de características que podrían anticipar un rebote
fuerte después de una corrección, en las 10 acciones BVC - siguiendo la
metodología acordada:

  1. Define el evento con precisión: un día "en corrección" (drawdown de
     al menos 5% desde el máximo de 20 días, medido al cierre del día
     ANTERIOR) es seguido, o no, por un día que cierra al menos +3% por
     encima de su propia apertura (un rebote fuerte).

  2. Mide ~19 características usando SOLO datos disponibles hasta el
     cierre del día anterior al evento (nunca el mismo día - eso sería
     ver el futuro).

  3. Compara cada característica entre el grupo que SÍ rebotó al día
     siguiente vs el que NO, con una prueba de permutación (no solo la
     diferencia de promedios) y corrección por comparaciones múltiples
     (Bonferroni) - para no repetir el error de "encontrar" un patrón
     falso por probar muchas cosas a la vez sin ajustar el umbral.

  4. Cualquier característica que sobreviva el paso 3 quedaría pendiente
     de validar fuera de muestra (calibración/validación), como hicimos
     con el drawdown.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_caracteristicas_rebote.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas_ta as ta
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings

_CRIPTOS_A_EXCLUIR = {"BTC-USD", "ETH-USD", "SOL-USD"}
ACTIVOS = [a for a in Settings.todos_los_activos() if a not in _CRIPTOS_A_EXCLUIR]

FECHA_INICIO = "2026-01-01"
UMBRAL_ANOMALIA = 15.0

UMBRAL_CORRECCION = 5.0   # % de drawdown mínimo para considerar "en corrección"
UMBRAL_REBOTE = 3.0       # % que debe cerrar por encima de su apertura para ser "rebote"
VENTANA_MAXIMO = 20
VENTANA_VOLUMEN = 20

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


def _calcular_caracteristicas(data):
    """Calcula todos los indicadores UNA vez sobre toda la serie (son
    causales - cada punto solo usa datos hasta ese momento por
    construcción propia de la fórmula). Devuelve None si algún indicador
    base no se pudo calcular (ej. datos insuficientes o degenerados para
    ese activo en particular) - en vez de fallar más adelante."""

    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"]
    open_ = data["Open"]

    rsi = ta.rsi(close, length=14)
    ema9 = ta.ema(close, length=9)
    ema21 = ta.ema(close, length=21)
    ema50 = ta.ema(close, length=50)
    macd_df = ta.macd(close)
    bbands = ta.bbands(close, length=20)
    atr = ta.atr(high, low, close, length=14)

    # Si algún indicador base no se pudo calcular (pandas_ta puede
    # devolver None en casos límite: muy pocos datos, precio degenerado,
    # etc.), no seguir - se trata como "datos insuficientes" para este
    # activo, en vez de fallar más adelante con un AttributeError.
    if rsi is None or ema9 is None or ema21 is None or ema50 is None or atr is None:
        return None
    if macd_df is None or "MACD_12_26_9" not in macd_df.columns:
        return None
    if bbands is None or "BBL_20_2.0_2.0" not in bbands.columns:
        return None

    vol_prom = volume.rolling(VENTANA_VOLUMEN).mean().shift(1)

    maximo_20 = close.rolling(VENTANA_MAXIMO).max().shift(1)
    minimo_20 = close.rolling(VENTANA_MAXIMO).min().shift(1)
    drawdown_pct = -((close - maximo_20) / maximo_20 * 100)

    variacion_diaria = ((close - close.shift(1)) / close.shift(1)) * 100
    es_rojo = variacion_diaria < 0

    caracteristicas = {}
    caracteristicas["rsi"] = rsi
    caracteristicas["dist_ema9_pct"] = (close - ema9) / ema9 * 100
    caracteristicas["dist_ema21_pct"] = (close - ema21) / ema21 * 100
    caracteristicas["dist_ema50_pct"] = (close - ema50) / ema50 * 100
    # MACD normalizado como % del precio - un MACD crudo no es comparable
    # entre activos de escalas de precio muy distintas (ej. una acción de
    # $300,000 COP vs una de $3 COP tendría un MACD miles de veces más
    # grande en valor absoluto, sin que eso signifique nada real).
    caracteristicas["macd_pct"] = (
        macd_df["MACD_12_26_9"] / close * 100 if macd_df is not None else None
    )
    caracteristicas["macd_hist_pct"] = (
        macd_df["MACDh_12_26_9"] / close * 100 if macd_df is not None else None
    )
    caracteristicas["macd_pendiente_pct"] = (
        (macd_df["MACD_12_26_9"] / close * 100) - (macd_df["MACD_12_26_9"] / close * 100).shift(3)
        if macd_df is not None else None
    )
    if bbands is not None:
        bbl = bbands["BBL_20_2.0_2.0"]
        bbu = bbands["BBU_20_2.0_2.0"]
        caracteristicas["bollinger_pctb"] = (close - bbl) / (bbu - bbl) * 100
    else:
        caracteristicas["bollinger_pctb"] = None
    caracteristicas["atr_relativo_pct"] = atr / close * 100
    caracteristicas["volumen_relativo"] = volume / vol_prom
    caracteristicas["volumen_relativo_tendencia_3d"] = (
        (volume / vol_prom).rolling(3).mean() / (volume / vol_prom).rolling(10).mean()
    )
    caracteristicas["drawdown_pct"] = drawdown_pct
    caracteristicas["dist_minimo20_pct"] = (close - minimo_20) / minimo_20 * 100
    caracteristicas["retorno_promedio_5d_pct"] = variacion_diaria.rolling(5).mean()
    caracteristicas["rsi_tendencia_3d"] = rsi - rsi.shift(3)
    caracteristicas["dias_rojos_consecutivos"] = es_rojo.groupby(
        (~es_rojo).cumsum()
    ).cumsum()
    caracteristicas["volumen_ultimo_dia_rojo_relativo"] = (
        (volume / vol_prom).where(es_rojo).ffill()
    )
    caracteristicas["posicion_cierre_en_rango_pct"] = (close - low) / (high - low) * 100
    caracteristicas["gap_apertura_pct"] = (open_ - close.shift(1)) / close.shift(1) * 100

    return caracteristicas


def _recolectar_filas(symbol, data, caracteristicas):
    """Para cada día 'en corrección' (medido al cierre del día anterior),
    arma una fila con las características de AYER y la etiqueta de si HOY
    fue un rebote fuerte o no."""

    filas = []
    n = len(data)

    open_ = data["Open"].values
    close = data["Close"].values
    drawdown = caracteristicas["drawdown_pct"]

    inicio = max(VENTANA_MAXIMO, 55)  # esperar a que EMA50/MACD tengan suficiente historia

    for i in range(inicio, n):
        dd_ayer = drawdown.iloc[i - 1]
        if dd_ayer != dd_ayer or dd_ayer < UMBRAL_CORRECCION:
            continue  # no estaba en corrección ayer, no aplica

        subida_hoy_pct = ((close[i] - open_[i]) / open_[i]) * 100
        etiqueta = 1 if subida_hoy_pct >= UMBRAL_REBOTE else 0

        fila = {"symbol": symbol, "etiqueta": etiqueta}
        for nombre, serie in caracteristicas.items():
            if serie is None:
                fila[nombre] = None
            else:
                valor = serie.iloc[i - 1]
                fila[nombre] = float(valor) if valor == valor else None

        filas.append(fila)

    return filas


def _prueba_permutacion_dos_grupos(valores_grupo1, valores_grupo2, n_permutaciones):
    """Prueba de permutación estándar para diferencia de promedios entre
    dos grupos - válida aquí porque cada fila es un día distinto (no hay
    ventanas superpuestas entre sí como en el estudio de drawdown)."""

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
    todas_las_filas = []

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, FECHA_INICIO)
        if data is None or len(data) < 80:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _limpiar_datos(data)
        caracteristicas = _calcular_caracteristicas(data)
        if caracteristicas is None:
            print(f"{symbol}: no se pudieron calcular los indicadores (datos insuficientes o degenerados), se omite")
            continue

        filas = _recolectar_filas(symbol, data, caracteristicas)
        todas_las_filas.extend(filas)

        print(f"{symbol}: {len(filas)} días en corrección encontrados")

    print()
    print(f"Total de días 'en corrección' recolectados (las 10 acciones): {len(todas_las_filas)}")

    grupo1 = [f for f in todas_las_filas if f["etiqueta"] == 1]  # SÍ rebotó fuerte al día siguiente
    grupo0 = [f for f in todas_las_filas if f["etiqueta"] == 0]  # NO rebotó

    print(f"Rebotaron fuerte al día siguiente: {len(grupo1)} | No rebotaron: {len(grupo0)}")
    print()

    nombres_caracteristicas = [
        "rsi", "dist_ema9_pct", "dist_ema21_pct", "dist_ema50_pct",
        "macd_pct", "macd_hist_pct", "macd_pendiente_pct", "bollinger_pctb",
        "atr_relativo_pct", "volumen_relativo", "volumen_relativo_tendencia_3d",
        "drawdown_pct", "dist_minimo20_pct", "retorno_promedio_5d_pct",
        "rsi_tendencia_3d", "dias_rojos_consecutivos",
        "volumen_ultimo_dia_rojo_relativo", "posicion_cierre_en_rango_pct",
        "gap_apertura_pct",
    ]

    umbral_bonferroni = 0.05 / len(nombres_caracteristicas)

    print("=" * 110)
    print(f"COMPARACIÓN POR CARACTERÍSTICA (umbral Bonferroni para {len(nombres_caracteristicas)} "
          f"pruebas: p < {umbral_bonferroni:.4f})")
    print("=" * 110)
    print(f"{'CARACTERÍSTICA':32} {'Prom. REBOTÓ':>14} {'Prom. NO rebotó':>16} "
          f"{'Diferencia':>12} {'p-valor':>10} {'¿Significativo?':>16}")
    print("-" * 110)

    resultados = []

    for nombre in nombres_caracteristicas:
        v1 = [f[nombre] for f in grupo1 if f[nombre] is not None]
        v0 = [f[nombre] for f in grupo0 if f[nombre] is not None]

        if len(v1) < 5 or len(v0) < 5:
            print(f"{nombre:32} datos insuficientes")
            continue

        diferencia, p_valor = _prueba_permutacion_dos_grupos(v1, v0, N_PERMUTACIONES)
        significativo = "SÍ" if p_valor < umbral_bonferroni else "no"

        resultados.append((nombre, diferencia, p_valor, significativo))

        print(f"{nombre:32} {np.mean(v1):>14.3f} {np.mean(v0):>16.3f} "
              f"{diferencia:>+12.3f} {p_valor:>10.4f} {significativo:>16}")

    print("-" * 110)

    sobrevivientes = [r for r in resultados if r[3] == "SÍ"]

    print()
    if sobrevivientes:
        print(f"Características que SOBREVIVEN la corrección de Bonferroni ({len(sobrevivientes)}):")
        for nombre, diferencia, p_valor, _ in sobrevivientes:
            print(f"  - {nombre}: diferencia {diferencia:+.3f}, p-valor {p_valor:.4f}")
        print()
        print("Pendiente: validar estas con calibración/validación fuera de muestra antes de confiar en ellas.")
    else:
        print("Ninguna característica sobrevive la corrección de Bonferroni - "
              "no hay evidencia de que alguna, medida así, distinga los rebotes reales del azar.")

    print("=" * 110)


if __name__ == "__main__":
    correr()