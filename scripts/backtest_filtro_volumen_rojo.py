"""
Prueba el filtro de "volumen del día rojo >= su promedio de 20 días"
(encontrado explorando ECOPETROL.CL y GEB.CL) sobre las OTRAS 8 acciones
BVC - nunca vistas al elegir el filtro - para saber si de verdad
generaliza o si fue casualidad de esas dos.

Compara, para cada una de las 8 acciones:
  - Racha verde + trailing stop SIN el filtro (como ya lo probamos)
  - Racha verde + trailing stop CON el filtro (solo entra si el volumen
    del día rojo fue >= 1.0x su promedio de 20 días anteriores)

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_filtro_volumen_rojo.py
    python scripts/backtest_filtro_volumen_rojo.py --umbral 1.0
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Las 8 acciones que NO se usaron para encontrar el patrón (Ecopetrol y GEB
# quedan fuera a propósito, para una prueba honesta fuera de muestra)
ACTIVOS = [
    "PFCIBEST.CL", "GRUPOARGOS.CL", "CEMARGOS.CL", "CELSIA.CL",
    "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

UMBRAL_ANOMALIA = 15.0
VENTANA_VOLUMEN = 20

STOP_INICIAL_PCT = 0.015
OBJETIVO_INICIAL_PCT = 0.03
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
class Operacion:
    entrada_fecha: object
    entrada_precio: float
    variacion_pct: float
    volumen_rojo_relativo: float


def _simular_operaciones(data, umbral_volumen, aplicar_filtro):
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

        vol_prom_rojo = volumen_promedio.iloc[idx_rojo]
        vol_rojo_relativo = (
            data["Volume"].iloc[idx_rojo] / vol_prom_rojo
            if vol_prom_rojo == vol_prom_rojo and vol_prom_rojo > 0 else None
        )

        if aplicar_filtro:
            if vol_rojo_relativo is None or vol_rojo_relativo < umbral_volumen:
                i += 1
                continue  # el filtro descarta esta señal

        entrada_precio = cierres[idx_verde]
        entrada_fecha = fechas[idx_verde]

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(data, idx_verde, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100

        operaciones.append(Operacion(
            entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            variacion_pct=variacion_pct, volumen_rojo_relativo=vol_rojo_relativo,
        ))

        i = idx_salida + 1

    return operaciones


def correr(fecha_inicio, umbral):
    print(f"Filtro probado: solo entrar si el volumen del día rojo >= {umbral:.2f}x su promedio de 20 días")
    print(f"Probado en las 8 acciones NO usadas para encontrar el patrón (Ecopetrol y GEB quedaron fuera)")
    print()

    resumen = {"sin_filtro": {"n": 0, "neto": 0.0}, "con_filtro": {"n": 0, "neto": 0.0}}

    for symbol in ACTIVOS:
        print("=" * 100)
        print(symbol)
        print("=" * 100)

        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < VENTANA_VOLUMEN + 10:
            print("  Sin datos suficientes.")
            print()
            continue

        data = _filtrar_anomalias(data)

        ops_sin_filtro = _simular_operaciones(data, umbral, aplicar_filtro=False)
        ops_con_filtro = _simular_operaciones(data, umbral, aplicar_filtro=True)

        neto_sin = sum(_calcular_dinero(op.variacion_pct) for op in ops_sin_filtro)
        neto_con = sum(_calcular_dinero(op.variacion_pct) for op in ops_con_filtro)

        print(f"  SIN filtro: {len(ops_sin_filtro):3} operaciones | neto ${neto_sin:+,.0f} COP")
        print(f"  CON filtro: {len(ops_con_filtro):3} operaciones | neto ${neto_con:+,.0f} COP")
        print()

        resumen["sin_filtro"]["n"] += len(ops_sin_filtro)
        resumen["sin_filtro"]["neto"] += neto_sin
        resumen["con_filtro"]["n"] += len(ops_con_filtro)
        resumen["con_filtro"]["neto"] += neto_con

    print("=" * 100)
    print("RESUMEN GENERAL (las 8 acciones fuera de muestra, juntas)")
    print("=" * 100)
    print(f"SIN filtro: {resumen['sin_filtro']['n']} operaciones | neto total ${resumen['sin_filtro']['neto']:+,.0f} COP")
    print(f"CON filtro: {resumen['con_filtro']['n']} operaciones | neto total ${resumen['con_filtro']['neto']:+,.0f} COP")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--umbral", type=float, default=1.0)
    args = parser.parse_args()

    correr(args.inicio, args.umbral)