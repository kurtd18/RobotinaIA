"""
Validación fuera de muestra para Time Series Momentum (TSMOM) - divide
todos los casos recolectados en calibración (primera mitad cronológica
de los MESES DE PRUEBA) y validación (segunda mitad, nunca vista), y
repite la comparación momentum positivo vs negativo por separado en cada
mitad.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/validacion_tsmom.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest_tsmom import (
    ACTIVOS, FECHA_INICIO, MESES_FORMACION,
    _cargar_datos_diarios, _limpiar_datos, _serie_mensual,
    _prueba_permutacion_dos_grupos, N_PERMUTACIONES,
)


def correr():
    series_mensuales = {}
    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, FECHA_INICIO)
        if data is None or len(data) < 40:
            continue
        data = _limpiar_datos(data)
        serie = _serie_mensual(data)
        if len(serie) >= MESES_FORMACION + 2:
            series_mensuales[symbol] = serie

    todos_los_periodos = sorted(set().union(*[set(s.index) for s in series_mensuales.values()]))

    periodos_prueba = todos_los_periodos[MESES_FORMACION + 1:]
    punto_medio_periodo = periodos_prueba[len(periodos_prueba) // 2]

    print(f"Períodos de prueba totales: {len(periodos_prueba)}")
    print(f"Calibración: hasta {punto_medio_periodo} (sin incluir) | Validación: desde {punto_medio_periodo}")
    print()

    resultados = {"CALIBRACIÓN": {"pos": [], "neg": []}, "VALIDACIÓN": {"pos": [], "neg": []}}

    for i in range(MESES_FORMACION, len(todos_los_periodos) - 1):
        periodo_formacion_inicio = todos_los_periodos[i - MESES_FORMACION]
        periodo_formacion_fin = todos_los_periodos[i]
        periodo_prueba = todos_los_periodos[i + 1]

        grupo = "CALIBRACIÓN" if periodo_prueba < punto_medio_periodo else "VALIDACIÓN"

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
                resultados[grupo]["pos"].append(retorno_mes_prueba)
            else:
                resultados[grupo]["neg"].append(retorno_mes_prueba)

    for nombre_grupo in ["CALIBRACIÓN", "VALIDACIÓN"]:
        pos = resultados[nombre_grupo]["pos"]
        neg = resultados[nombre_grupo]["neg"]

        print("=" * 100)
        print(f"{nombre_grupo}")
        print("=" * 100)
        print(f"Momentum positivo: {len(pos)} casos | retorno promedio: {np.mean(pos):+.3f}%")
        print(f"Momentum negativo: {len(neg)} casos | retorno promedio: {np.mean(neg):+.3f}%")

        if len(pos) >= 20 and len(neg) >= 20:
            diferencia, p_valor = _prueba_permutacion_dos_grupos(pos, neg, N_PERMUTACIONES)
            print(f"Diferencia: {diferencia:+.3f} puntos porcentuales | p-valor: {p_valor:.4f}")
        else:
            print("Muestra insuficiente en esta mitad.")
        print()


if __name__ == "__main__":
    correr()