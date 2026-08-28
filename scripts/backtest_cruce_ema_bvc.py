"""
Backtest de "cruce de EMA" (EMA9 cruza por encima de EMA21) como señal de
entrada, combinado con el trailing stop real que ya validamos, sobre las
10 acciones BVC.

Lógica de entrada:
  Se detecta el MOMENTO EXACTO en que la EMA9 cruza de abajo hacia arriba
  de la EMA21 (el día anterior EMA9 <= EMA21, y hoy EMA9 > EMA21) - no es
  "está por encima" de forma continua (eso ya se probó antes con el score
  y no mostró ventaja), es específicamente el evento del cruce.

  Se compra al cierre del día que confirma el cruce.

Salida: mismo trailing stop real (stop inicial -1.5%, objetivo inicial
+3%, incrementos de +1%).

Dinero: mismo método validado (desembolso $5,000,000 COP, comisión
$7,000 COP por lado, descontada del desembolso/lo recibido al vender).

Usa velas DIARIAS desde el 1 de enero de 2026 (o la fecha que se indique).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_cruce_ema_bvc.py
    python scripts/backtest_cruce_ema_bvc.py --inicio 2026-01-01 --rapida 9 --lenta 21
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas_ta as ta
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = [
    "PFCIBEST.CL",   # Bancolombia Preferencial
    "ECOPETROL.CL",  # Ecopetrol
    "GEB.CL",        # Grupo Energía Bogotá
    "GRUPOARGOS.CL", # Grupo Argos
    "CEMARGOS.CL",   # Cementos Argos
    "CELSIA.CL",     # Celsia
    "GRUPOSURA.CL",  # Grupo Sura
    "PFDAVVNDA.CL",  # Davivienda Preferencial
    "TERPEL.CL",     # Organización Terpel
    "NUTRESA.CL",    # Grupo Nutresa
]

UMBRAL_ANOMALIA = 15.0

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
    return data.drop(index=anomalos), len(anomalos)


def _detectar_cruces(data, rapida, lenta):
    """Devuelve la lista de índices donde la EMA rápida cruza de abajo
    hacia arriba de la EMA lenta (cruce alcista)."""

    ema_rapida = ta.ema(data["Close"], length=rapida)
    ema_lenta = ta.ema(data["Close"], length=lenta)

    cruces = []
    for i in range(1, len(data)):
        if ema_rapida.iloc[i] is None or ema_lenta.iloc[i] is None:
            continue
        if ema_rapida.iloc[i] != ema_rapida.iloc[i] or ema_lenta.iloc[i] != ema_lenta.iloc[i]:
            continue  # NaN, todavía no hay suficiente historia

        estaba_abajo = ema_rapida.iloc[i - 1] <= ema_lenta.iloc[i - 1]
        esta_arriba = ema_rapida.iloc[i] > ema_lenta.iloc[i]

        if estaba_abajo and esta_arriba:
            cruces.append(i)

    return cruces


def _simular_trailing_stop(data, idx_entrada, entrada_precio):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + OBJETIVO_INICIAL_PCT)

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
class Operacion:
    entrada_fecha: object
    entrada_precio: float
    salida_fecha: object
    salida_precio: float
    resultado: str
    variacion_pct: float


def _simular_operaciones(data, rapida, lenta):
    cruces = _detectar_cruces(data, rapida, lenta)

    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in cruces:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100

        operaciones.append(Operacion(
            entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            salida_fecha=salida_fecha, salida_precio=salida_precio,
            resultado=resultado, variacion_pct=variacion_pct,
        ))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def correr(fecha_inicio, rapida, lenta):
    print(f"Entrada: cruce alcista EMA{rapida} sobre EMA{lenta}")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}% inicial, "
          f"+{OBJETIVO_INICIAL_PCT*100:.0f}% objetivo inicial, +{INCREMENTO_PCT*100:.0f}% incrementos)")
    print(f"Desembolso: ${DESEMBOLSO_TOTAL:,.0f} COP | Comisión: ${COMISION:,.0f} COP/lado")
    print()

    neto_total_general = 0.0
    operaciones_total_general = 0
    ganadoras_general = 0
    perdedoras_general = 0

    for symbol in ACTIVOS:
        print("=" * 100)
        print(symbol)
        print("=" * 100)

        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < lenta + 10:
            print("  Sin datos suficientes.")
            print()
            continue

        data, n_anomalos = _filtrar_anomalias(data)
        if n_anomalos > 0:
            print(f"  ({n_anomalos} día(s) excluido(s) por movimiento anómalo, probable split)")

        print(f"  Rango: {data.index[0].strftime('%Y-%m-%d')} a {data.index[-1].strftime('%Y-%m-%d')} "
              f"({len(data)} días)")

        operaciones = _simular_operaciones(data, rapida, lenta)

        if not operaciones:
            print("  No se generaron operaciones (no hubo cruces alcistas).")
            print()
            continue

        neto_symbol = 0.0
        ganaron = 0
        perdieron = 0

        for op in operaciones:
            neto = _calcular_dinero(op.variacion_pct)
            neto_symbol += neto

            if neto > 0:
                ganaron += 1
            else:
                perdieron += 1

            print(f"  Compra {op.entrada_fecha.strftime('%Y-%m-%d')} @ ${op.entrada_precio:,.2f}  ->  "
                  f"Venta {op.salida_fecha.strftime('%Y-%m-%d')} @ ${op.salida_precio:,.2f} | "
                  f"{op.resultado:12} | {op.variacion_pct:+.2f}% | neto {neto:+,.0f} COP")

        print("-" * 100)
        print(f"  Operaciones: {len(operaciones)} (netas positivas={ganaron} negativas={perdieron})")
        print(f"  Resultado neto de {symbol}: ${neto_symbol:+,.0f} COP")
        print()

        neto_total_general += neto_symbol
        operaciones_total_general += len(operaciones)
        ganadoras_general += ganaron
        perdedoras_general += perdieron

    print("=" * 100)
    print("RESUMEN GENERAL (las 10 acciones juntas)")
    print("=" * 100)
    print(f"Total de operaciones: {operaciones_total_general} "
          f"(netas positivas={ganadoras_general} negativas={perdedoras_general})")
    print(f"Capital total desembolsado: ${operaciones_total_general * DESEMBOLSO_TOTAL:,.0f} COP")
    print(f"Resultado neto total: ${neto_total_general:+,.0f} COP")
    if operaciones_total_general < 30:
        print("⚠️  Muestra menor a 30 operaciones - no es suficiente para conclusiones firmes.")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--rapida", type=int, default=9)
    parser.add_argument("--lenta", type=int, default=21)
    args = parser.parse_args()

    correr(args.inicio, args.rapida, args.lenta)