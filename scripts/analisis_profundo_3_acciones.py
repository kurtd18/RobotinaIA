"""
Análisis detallado de las señales de Market Profile para PFCIBEST.CL,
ECOPETROL.CL y CELSIA.CL - muestra la trayectoria de precio de los 10
días previos a cada entrada, el nivel de Value Area roto, el volumen
relativo, y el resultado final - para analizar con datos reales qué
caracteriza a las entradas ganadoras vs las perdedoras.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_profundo_3_acciones.py
    python scripts/analisis_profundo_3_acciones.py --ventana 50 --objetivo 0.015
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = ["PFCIBEST.CL", "ECOPETROL.CL", "CELSIA.CL"]

UMBRAL_ANOMALIA = 15.0
N_BINS = 20
VENTANA_VOLUMEN = 20

STOP_INICIAL_PCT = 0.015
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


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


def _value_area_high(data, idx, ventana, n_bins):
    if idx < ventana:
        return None

    v = data.iloc[idx - ventana: idx]
    pmin, pmax = float(v["Low"].min()), float(v["High"].max())
    if pmax <= pmin:
        return None

    bins = np.linspace(pmin, pmax, n_bins + 1)
    idx_bin = np.clip(np.digitize(v["Close"], bins) - 1, 0, n_bins - 1)

    tiempo_bin = np.zeros(n_bins)
    for i_bin in idx_bin:
        tiempo_bin[i_bin] += 1

    orden = np.argsort(tiempo_bin)[::-1]
    total = tiempo_bin.sum()
    acumulado, bins_va = 0, []
    for i_bin in orden:
        acumulado += tiempo_bin[i_bin]
        bins_va.append(i_bin)
        if acumulado >= total * 0.70:
            break

    vah_bin = max(bins_va)
    return bins[vah_bin + 1]


def _detectar_rupturas_value_area(data, ventana, n_bins):
    rupturas = []
    for i in range(ventana, len(data)):
        vah = _value_area_high(data, i, ventana, n_bins)
        if vah is None:
            continue
        if float(data["Close"].iloc[i]) > vah:
            rupturas.append((i, vah))
    return rupturas


def _simular_trailing_stop(data, idx_entrada, entrada_precio, objetivo_inicial_pct):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + objetivo_inicial_pct)

    n = len(data)

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]

        if low <= stop:
            return "VENDIO", float(stop), data.index[i]

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + INCREMENTO_PCT)

    precio_final = float(data["Close"].iloc[-1])
    return "SIN_RESOLVER", precio_final, data.index[-1]


@dataclass
class OperacionDetallada:
    symbol: str
    entrada_fecha: object
    entrada_precio: float
    vah_roto: float
    distancia_al_vah_pct: float
    trayectoria_10dias: list
    volumen_relativo: float
    resultado: str
    variacion_pct: float
    neto: float


def _analizar(symbol, data, ventana, n_bins, objetivo_inicial_pct):
    volumen_promedio = data["Volume"].rolling(VENTANA_VOLUMEN).mean().shift(1)

    rupturas = _detectar_rupturas_value_area(data, ventana, n_bins)

    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada, vah in rupturas:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        distancia_al_vah_pct = ((entrada_precio - vah) / vah) * 100

        inicio_trayectoria = max(0, idx_entrada - 9)
        trayectoria = data["Close"].iloc[inicio_trayectoria: idx_entrada + 1].tolist()

        vol_prom = volumen_promedio.iloc[idx_entrada]
        vol_relativo = (
            float(data["Volume"].iloc[idx_entrada]) / vol_prom
            if vol_prom == vol_prom and vol_prom > 0 else None
        )

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(
            data, idx_entrada, entrada_precio, objetivo_inicial_pct
        )

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)

        operaciones.append(OperacionDetallada(
            symbol=symbol, entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            vah_roto=vah, distancia_al_vah_pct=distancia_al_vah_pct,
            trayectoria_10dias=trayectoria, volumen_relativo=vol_relativo,
            resultado=resultado, variacion_pct=variacion_pct, neto=neto,
        ))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def correr(fecha_inicio, ventana, objetivo_inicial_pct):
    todas_operaciones = []

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < ventana + 20:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _filtrar_anomalias(data)
        operaciones = _analizar(symbol, data, ventana, N_BINS, objetivo_inicial_pct)
        todas_operaciones.extend(operaciones)

        print("=" * 100)
        print(symbol)
        print("=" * 100)

        for op in operaciones:
            trayectoria_str = " -> ".join(f"{p:,.2f}" for p in op.trayectoria_10dias)
            vol_str = f"{op.volumen_relativo:.2f}x" if op.volumen_relativo else "N/A"

            print(f"  Entrada {op.entrada_fecha.strftime('%Y-%m-%d')} @ ${op.entrada_precio:,.2f} | "
                  f"VAH roto: ${op.vah_roto:,.2f} (+{op.distancia_al_vah_pct:.2f}% sobre el VAH) | "
                  f"Volumen: {vol_str}")
            print(f"    Trayectoria (10 días previos a la entrada, incluida): {trayectoria_str}")
            print(f"    Resultado: {op.resultado} | {op.variacion_pct:+.2f}% | neto {op.neto:+,.0f} COP")
            print()

    print()
    print("=" * 100)
    print("COMPARACIÓN: GANADORAS vs PERDEDORAS (las 3 acciones juntas)")
    print("=" * 100)

    ganadoras = [op for op in todas_operaciones if op.neto > 0]
    perdedoras = [op for op in todas_operaciones if op.neto <= 0]

    print(f"Ganadoras: {len(ganadoras)} | Perdedoras: {len(perdedoras)}")
    print()

    def _promedio(vals):
        v = [x for x in vals if x is not None]
        return sum(v) / len(v) if v else None

    dist_g = _promedio([op.distancia_al_vah_pct for op in ganadoras])
    dist_p = _promedio([op.distancia_al_vah_pct for op in perdedoras])
    vol_g = _promedio([op.volumen_relativo for op in ganadoras])
    vol_p = _promedio([op.volumen_relativo for op in perdedoras])

    print(f"Distancia sobre el VAH al entrar (%):  Ganadoras: {dist_g:.3f}  |  Perdedoras: {dist_p:.3f}"
          if dist_g is not None and dist_p is not None else "Distancia sobre VAH: datos insuficientes")
    print(f"Volumen relativo al entrar:             Ganadoras: {vol_g:.3f}  |  Perdedoras: {vol_p:.3f}"
          if vol_g is not None and vol_p is not None else "Volumen relativo: datos insuficientes")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--ventana", type=int, default=50)
    parser.add_argument("--objetivo", type=float, default=0.015)
    args = parser.parse_args()

    correr(args.inicio, args.ventana, args.objetivo)