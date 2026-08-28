"""
Analiza las operaciones de "racha verde + trailing stop" para uno o más
activos, y compara características medibles entre las GANADORAS y las
PERDEDORAS - para encontrar, con evidencia, qué distingue a unas de
otras (no adivinando, midiendo).

Características medidas por cada operación:
  - Caída del día rojo (%, cierre vs cierre del día anterior)
  - Subida del día verde/entrada (%, cierre vs cierre del día rojo)
  - Volumen del día verde/entrada vs su propio promedio de 20 días
  - Volumen del día rojo vs su propio promedio de 20 días

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_patron_entrada.py
    python scripts/analisis_patron_entrada.py --activos ECOPETROL.CL,GEB.CL
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UMBRAL_ANOMALIA = 15.0

STOP_INICIAL_PCT = 0.015
OBJETIVO_INICIAL_PCT = 0.03
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

VENTANA_VOLUMEN = 20


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


def _simular_trailing_stop(data, entrada_idx, entrada_precio):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + OBJETIVO_INICIAL_PCT)

    n = len(data)

    for i in range(entrada_idx + 1, n):
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
class OperacionConPatron:
    symbol: str
    fecha_rojo: object
    caida_rojo_pct: float
    volumen_rojo_relativo: float
    fecha_verde: object
    subida_verde_pct: float
    volumen_verde_relativo: float
    resultado: str
    variacion_pct: float
    neto: float


def _analizar_con_patron(symbol, data):
    # .shift(1) para que el promedio de cada día NO incluya su propio
    # volumen - se compara contra los 20 días ANTERIORES solamente.
    volumen_promedio = data["Volume"].rolling(VENTANA_VOLUMEN).mean().shift(1)

    cierres = data["Close"].values
    fechas = data.index
    n = len(cierres)

    operaciones = []
    i = 1

    while i < n:
        es_rojo = cierres[i] < cierres[i - 1]

        if not es_rojo:
            i += 1
            continue

        if i + 1 >= n or cierres[i + 1] <= cierres[i]:
            i += 1
            continue

        idx_rojo = i
        idx_verde = i + 1

        caida_rojo_pct = ((cierres[idx_rojo] - cierres[idx_rojo - 1]) / cierres[idx_rojo - 1]) * 100
        subida_verde_pct = ((cierres[idx_verde] - cierres[idx_rojo]) / cierres[idx_rojo]) * 100

        vol_prom_rojo = volumen_promedio.iloc[idx_rojo]
        vol_prom_verde = volumen_promedio.iloc[idx_verde]

        vol_rojo_relativo = (
            data["Volume"].iloc[idx_rojo] / vol_prom_rojo
            if vol_prom_rojo == vol_prom_rojo and vol_prom_rojo > 0 else None
        )
        vol_verde_relativo = (
            data["Volume"].iloc[idx_verde] / vol_prom_verde
            if vol_prom_verde == vol_prom_verde and vol_prom_verde > 0 else None
        )

        entrada_precio = cierres[idx_verde]

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(data, idx_verde, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)

        operaciones.append(OperacionConPatron(
            symbol=symbol,
            fecha_rojo=fechas[idx_rojo], caida_rojo_pct=caida_rojo_pct, volumen_rojo_relativo=vol_rojo_relativo,
            fecha_verde=fechas[idx_verde], subida_verde_pct=subida_verde_pct, volumen_verde_relativo=vol_verde_relativo,
            resultado=resultado, variacion_pct=variacion_pct, neto=neto,
        ))

        i = idx_salida + 1

    return operaciones


def _promedio(valores):
    valores_validos = [v for v in valores if v is not None]
    if not valores_validos:
        return None
    return sum(valores_validos) / len(valores_validos)


def correr(activos, fecha_inicio):
    todas_operaciones = []

    for symbol in activos:
        print(f"Procesando {symbol}...")
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < VENTANA_VOLUMEN + 10:
            print(f"  Sin datos suficientes.")
            continue

        data = _filtrar_anomalias(data)
        operaciones = _analizar_con_patron(symbol, data)
        todas_operaciones.extend(operaciones)

    print()
    print("=" * 100)
    print("DETALLE DE CADA OPERACIÓN")
    print("=" * 100)
    print(f"{'SYMBOL':13} {'ROJO':10} {'CAÍDA%':>8} {'VOL.ROJO':>9} {'VERDE':10} {'SUBE%':>7} "
          f"{'VOL.VERDE':>9} {'RESULT':12} {'NETO':>12}")
    print("-" * 100)

    for op in todas_operaciones:
        vol_r = f"{op.volumen_rojo_relativo:.2f}x" if op.volumen_rojo_relativo else "N/A"
        vol_v = f"{op.volumen_verde_relativo:.2f}x" if op.volumen_verde_relativo else "N/A"
        print(f"{op.symbol:13} {op.fecha_rojo.strftime('%Y-%m-%d'):10} {op.caida_rojo_pct:>7.2f}% "
              f"{vol_r:>9} {op.fecha_verde.strftime('%Y-%m-%d'):10} {op.subida_verde_pct:>6.2f}% "
              f"{vol_v:>9} {op.resultado:12} {op.neto:>+11,.0f}")

    print("-" * 100)
    print()

    ganadoras = [op for op in todas_operaciones if op.neto > 0]
    perdedoras = [op for op in todas_operaciones if op.neto <= 0]

    print("=" * 100)
    print(f"COMPARACIÓN: GANADORAS (n={len(ganadoras)}) vs PERDEDORAS (n={len(perdedoras)})")
    print("=" * 100)

    caracteristicas = [
        ("Caída del día rojo (%)", lambda op: op.caida_rojo_pct),
        ("Volumen del día rojo (relativo a su promedio)", lambda op: op.volumen_rojo_relativo),
        ("Subida del día verde (%)", lambda op: op.subida_verde_pct),
        ("Volumen del día verde (relativo a su promedio)", lambda op: op.volumen_verde_relativo),
    ]

    for nombre, extractor in caracteristicas:
        prom_ganadoras = _promedio([extractor(op) for op in ganadoras])
        prom_perdedoras = _promedio([extractor(op) for op in perdedoras])

        pg = f"{prom_ganadoras:.3f}" if prom_ganadoras is not None else "N/A"
        pp = f"{prom_perdedoras:.3f}" if prom_perdedoras is not None else "N/A"

        print(f"{nombre:48} | Ganadoras: {pg:>10} | Perdedoras: {pp:>10}")

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activos", type=str, default="ECOPETROL.CL,GEB.CL")
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    args = parser.parse_args()

    activos = args.activos.split(",")

    correr(activos, args.inicio)