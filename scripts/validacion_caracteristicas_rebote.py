"""
Validación fuera de muestra (Paso 4 de la metodología acordada) para las
3 características que sobrevivieron la corrección de Bonferroni en
analisis_caracteristicas_rebote_63.py: dist_ema50_pct, macd_pct,
atr_relativo_pct.

Divide todos los días "en corrección" recolectados en calibración
(primera mitad cronológica) y validación (segunda mitad, nunca vista) -
y repite la misma comparación de grupos (rebotó vs no rebotó) por
separado en cada mitad, para confirmar si la diferencia se sostiene con
consistencia, o si era un patrón que solo aparecía en parte del período.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/validacion_caracteristicas_rebote.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analisis_caracteristicas_rebote_63 import (
    ACTIVOS, FECHA_INICIO, _cargar_datos_diarios, _limpiar_datos,
    _calcular_caracteristicas, VENTANA_MAXIMO, UMBRAL_CORRECCION, UMBRAL_REBOTE,
    _prueba_permutacion_dos_grupos, N_PERMUTACIONES,
)

CARACTERISTICAS_A_VALIDAR = ["dist_ema50_pct", "macd_pct", "atr_relativo_pct"]


def _recolectar_filas_con_fecha(symbol, data, caracteristicas):
    """Igual que _recolectar_filas del script original, pero además
    guarda la fecha de cada fila, para poder dividir cronológicamente."""

    filas = []
    n = len(data)

    open_ = data["Open"].values
    close = data["Close"].values
    drawdown = caracteristicas["drawdown_pct"]

    inicio = max(VENTANA_MAXIMO, 55)

    for i in range(inicio, n):
        dd_ayer = drawdown.iloc[i - 1]
        if dd_ayer != dd_ayer or dd_ayer < UMBRAL_CORRECCION:
            continue

        subida_hoy_pct = ((close[i] - open_[i]) / open_[i]) * 100
        etiqueta = 1 if subida_hoy_pct >= UMBRAL_REBOTE else 0

        fila = {"symbol": symbol, "etiqueta": etiqueta, "fecha": data.index[i]}
        for nombre, serie in caracteristicas.items():
            if serie is None:
                fila[nombre] = None
            else:
                valor = serie.iloc[i - 1]
                fila[nombre] = float(valor) if valor == valor else None

        filas.append(fila)

    return filas


def correr():
    todas_las_filas = []

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, FECHA_INICIO)
        if data is None or len(data) < 80:
            continue

        data = _limpiar_datos(data)
        caracteristicas = _calcular_caracteristicas(data)
        if caracteristicas is None:
            continue

        filas = _recolectar_filas_con_fecha(symbol, data, caracteristicas)
        todas_las_filas.extend(filas)

    todas_las_filas.sort(key=lambda f: f["fecha"])

    punto_medio = len(todas_las_filas) // 2
    calibracion = todas_las_filas[:punto_medio]
    validacion = todas_las_filas[punto_medio:]

    fecha_corte = calibracion[-1]["fecha"] if calibracion else None
    print(f"Total de filas: {len(todas_las_filas)}")
    print(f"Calibración: {len(calibracion)} filas (hasta {fecha_corte.strftime('%Y-%m-%d') if fecha_corte else '?'})")
    print(f"Validación: {len(validacion)} filas (después de esa fecha, nunca vista en calibración)")
    print()

    for nombre_grupo, filas_grupo in [("CALIBRACIÓN", calibracion), ("VALIDACIÓN", validacion)]:
        grupo1 = [f for f in filas_grupo if f["etiqueta"] == 1]
        grupo0 = [f for f in filas_grupo if f["etiqueta"] == 0]

        print("=" * 100)
        print(f"{nombre_grupo}: {len(grupo1)} rebotaron, {len(grupo0)} no rebotaron")
        print("=" * 100)
        print(f"{'CARACTERÍSTICA':22} {'Prom. REBOTÓ':>14} {'Prom. NO rebotó':>16} "
              f"{'Diferencia':>12} {'p-valor':>10}")
        print("-" * 100)

        for nombre in CARACTERISTICAS_A_VALIDAR:
            v1 = [f[nombre] for f in grupo1 if f[nombre] is not None]
            v0 = [f[nombre] for f in grupo0 if f[nombre] is not None]

            if len(v1) < 5 or len(v0) < 5:
                print(f"{nombre:22} datos insuficientes en esta mitad (n1={len(v1)}, n0={len(v0)})")
                continue

            diferencia, p_valor = _prueba_permutacion_dos_grupos(v1, v0, N_PERMUTACIONES)
            print(f"{nombre:22} {np.mean(v1):>14.3f} {np.mean(v0):>16.3f} {diferencia:>+12.3f} {p_valor:>10.4f}")

        print()


if __name__ == "__main__":
    correr()
    