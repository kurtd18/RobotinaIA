"""
Calibra los parámetros del trailing stop (stop inicial, objetivo inicial,
incremento) específicamente para TERPEL.CL y NUTRESA.CL, en vez de asumir
que el mismo -1.5%/+3%/+1% que usamos para las otras 8 acciones también
les sirve a estas dos.

Fase 1 (calibración): barrido de combinaciones sobre la PRIMERA MITAD
cronológica de las señales "racha verde" de cada acción.

Fase 2 (validación): aplica la mejor combinación de la Fase 1 sobre la
SEGUNDA MITAD - datos que el barrido nunca vio - para confirmar si de
verdad mejora algo o es casualidad del período de calibración (esto es
lo que evita el error que ya cometimos una vez con el filtro de volumen).

Dinero: mismo método validado (desembolso $5,000,000 COP, comisión
$7,000 COP por lado).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/calibrar_trailing_terpel_nutresa.py
    python scripts/calibrar_trailing_terpel_nutresa.py --activos TERPEL.CL,NUTRESA.CL
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS_DEFAULT = ["TERPEL.CL", "NUTRESA.CL"]

UMBRAL_ANOMALIA = 15.0

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

# Cuadrícula de combinaciones a probar: (stop_inicial, objetivo_inicial, incremento)
GRID = [
    (0.010, 0.020, 0.010),
    (0.010, 0.030, 0.010),
    (0.015, 0.020, 0.010),
    (0.015, 0.030, 0.010),  # la que usamos para todas hasta ahora
    (0.015, 0.030, 0.015),
    (0.020, 0.030, 0.010),
    (0.020, 0.040, 0.015),
    (0.020, 0.040, 0.020),
    (0.025, 0.040, 0.015),
    (0.025, 0.050, 0.020),
    (0.030, 0.050, 0.020),
    (0.030, 0.060, 0.030),
]

MIN_SENALES_CALIBRACION = 5


def _cargar_datos_diarios(symbol, fecha_inicio):
    data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_entradas(data):
    """Detecta los puntos de entrada de 'racha verde' (rojo->verde
    confirmado) UNA sola vez - se reutilizan para probar todas las
    combinaciones de la cuadrícula."""

    cierres = data["Close"].values
    n = len(cierres)

    entradas = []
    i = 1
    while i < n - 1:
        es_rojo = cierres[i] < cierres[i - 1]
        if es_rojo and cierres[i + 1] > cierres[i]:
            entradas.append(i + 1)
        i += 1

    return entradas


def _simular_trailing_stop(data, idx_entrada, entrada_precio, stop_inicial_pct, objetivo_inicial_pct, incremento_pct):
    stop = entrada_precio * (1 - stop_inicial_pct)
    objetivo = entrada_precio * (1 + objetivo_inicial_pct)

    n = len(data)

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]

        if low <= stop:
            return float(stop), data.index[i]

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + incremento_pct)

    return float(data["Close"].iloc[-1]), data.index[-1]


def _simular_grupo_entradas(data, indices_entrada, stop_inicial_pct, objetivo_inicial_pct, incremento_pct):
    """Simula un grupo de entradas SIN solaparse (si una sigue abierta
    cuando debería abrirse la siguiente, se salta esa siguiente)."""

    variaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        salida_precio, salida_fecha = _simular_trailing_stop(
            data, idx_entrada, entrada_precio, stop_inicial_pct, objetivo_inicial_pct, incremento_pct
        )

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        variaciones.append(variacion_pct)

        en_posicion_hasta_idx = idx_salida

    return variaciones


def _dividir_calibracion_validacion(indices_entrada):
    punto_medio = len(indices_entrada) // 2
    return indices_entrada[:punto_medio], indices_entrada[punto_medio:]


def correr(activos, fecha_inicio):
    for symbol in activos:
        print("=" * 100)
        print(symbol)
        print("=" * 100)

        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < 20:
            print("  Sin datos suficientes.")
            continue

        data = _filtrar_anomalias(data)
        entradas = _detectar_entradas(data)

        calib, valid = _dividir_calibracion_validacion(entradas)
        print(f"  Señales totales: {len(entradas)} (calibración={len(calib)}, validación={len(valid)})")
        print()

        if len(calib) < MIN_SENALES_CALIBRACION:
            print("  Muestra de calibración insuficiente, se omite el barrido.")
            print()
            continue

        print(f"  {'STOP':>7} {'OBJETIVO':>9} {'INCREM.':>8} {'N':>4} {'NETO PROMEDIO':>16}")
        print("  " + "-" * 60)

        mejor_combo = None
        mejor_neto_promedio = float("-inf")

        for stop_pct, objetivo_pct, incremento_pct in GRID:
            variaciones = _simular_grupo_entradas(data, calib, stop_pct, objetivo_pct, incremento_pct)
            if not variaciones:
                continue

            netos = [_calcular_dinero(v) for v in variaciones]
            neto_promedio = sum(netos) / len(netos)

            print(f"  {stop_pct*100:>6.1f}% {objetivo_pct*100:>8.1f}% {incremento_pct*100:>7.1f}% "
                  f"{len(variaciones):>4} ${neto_promedio:>+15,.0f}")

            if neto_promedio > mejor_neto_promedio:
                mejor_neto_promedio = neto_promedio
                mejor_combo = (stop_pct, objetivo_pct, incremento_pct)

        print()

        if mejor_combo is None:
            print("  No se encontró combinación válida.")
            print()
            continue

        print(f"  Mejor combinación en calibración: stop={mejor_combo[0]*100:.1f}% "
              f"objetivo={mejor_combo[1]*100:.1f}% incremento={mejor_combo[2]*100:.1f}% "
              f"(neto promedio ${mejor_neto_promedio:+,.0f})")
        print()

        print("  --- Validación fuera de muestra (segunda mitad, nunca vista en el barrido) ---")

        for nombre, (s, o, inc) in [
            ("ORIGINAL (-1.5%/+3%/+1%)", (0.015, 0.03, 0.01)),
            (f"MEJOR CALIBRADA ({mejor_combo[0]*100:.1f}%/{mejor_combo[1]*100:.1f}%/{mejor_combo[2]*100:.1f}%)", mejor_combo),
        ]:
            variaciones_valid = _simular_grupo_entradas(data, valid, s, o, inc)
            if not variaciones_valid:
                print(f"  {nombre}: sin operaciones en validación")
                continue

            netos_valid = [_calcular_dinero(v) for v in variaciones_valid]
            neto_total = sum(netos_valid)
            neto_prom = neto_total / len(netos_valid)

            print(f"  {nombre}: n={len(variaciones_valid)} | neto total ${neto_total:+,.0f} | "
                  f"promedio ${neto_prom:+,.0f}/operación")

        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activos", type=str, default=",".join(ACTIVOS_DEFAULT))
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    args = parser.parse_args()

    activos = args.activos.split(",")

    correr(activos, args.inicio)