"""
Backtest enfocado en 10 acciones de la BVC, con la regla de salida C
(objetivo +3% / stop -2%) y horizonte de 3 días reales, mostrando el
resultado en dinero por cada acción por separado.

Tickers usados (ver notas de las 3 acciones que necesitan verificación):
  1. PFCIBEST.CL   - Bancolombia Preferencial (renombrada a Grupo Cibest;
                     PFBCOLOM.CL ya no tiene datos en Yahoo Finance)
  2. ECOPETROL.CL  - Ecopetrol
  3. GEB.CL        - Grupo Energía Bogotá
  4. GRUPOARGOS.CL - Grupo Argos
  5. CEMARGOS.CL   - Cementos Argos
  6. CELSIA.CL     - Celsia
  7. GRUPOSURA.CL  - Grupo Sura
  8. PFDAVVNDA.CL  - Davivienda Preferencial (SIN VERIFICAR - DAVIVIENDA.CL
                     sin el "PF" ya se confirmó que no tiene datos)
  9. TERPEL.CL     - Organización Terpel (SIN VERIFICAR - nunca antes probado)
  10. NUTRESA.CL   - Grupo Nutresa

Método de cálculo del dinero:
  - Desembolso total por operación: $5,000,000 COP
  - Comisión de entrada ($7,000) sale DE ESE monto -> lo que realmente se
    invierte en el activo es $4,993,000
  - Ese monto crece/decrece según la variación de la operación
  - Al vender, se descuenta otra comisión de $7,000 de lo recibido
  - Resultado neto = (valor recibido al vender) - $5,000,000 desembolsados

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_4_bvc.py
    python scripts/backtest_4_bvc.py --dias 60
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings
from scoring import calcular_score

TZ_BOGOTA = ZoneInfo("America/Bogota")

MIN_VELAS_PARA_SCORE = 40
HORIZONTE_TIEMPO = timedelta(days=3)
MAX_VELAS_SIMULACION_ABS = 900
PASO_VELAS = 3

OBJETIVO_PCT = 0.03  # opción C
STOP_PCT = 0.02      # opción C

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000

ACTIVOS = [
    "PFCIBEST.CL",   # Bancolombia Preferencial (renombrada a Grupo Cibest)
    "ECOPETROL.CL",  # Ecopetrol
    "GEB.CL",        # Grupo Energía Bogotá
    "GRUPOARGOS.CL", # Grupo Argos
    "CEMARGOS.CL",   # Cementos Argos
    "CELSIA.CL",     # Celsia
    "GRUPOSURA.CL",  # Grupo Sura
    "PFDAVVNDA.CL",  # Davivienda Preferencial - SIN VERIFICAR
    "TERPEL.CL",     # Organización Terpel - SIN VERIFICAR
    "NUTRESA.CL",    # Grupo Nutresa
]


@dataclass
class Entrada:
    idx: int
    entrada_ts: object
    entrada_precio: float


def _cargar_datos(symbol, dias):
    data = yf.Ticker(symbol).history(period=f"{dias}d", interval="5m")
    if data.empty:
        return None
    data.index = data.index.tz_convert(TZ_BOGOTA)
    return data


def _detectar_entradas(data):
    entradas = []
    en_posicion_hasta = -1

    for i in range(MIN_VELAS_PARA_SCORE, len(data), PASO_VELAS):
        if i <= en_posicion_hasta:
            continue

        data_hasta_aqui = data.iloc[: i + 1]

        try:
            score, precio = calcular_score(data_hasta_aqui)
        except Exception:
            continue

        if score >= Settings.UMBRAL_SENAL:
            entradas.append(Entrada(idx=i, entrada_ts=data.index[i], entrada_precio=precio))
            en_posicion_hasta = i + MAX_VELAS_SIMULACION_ABS

    return entradas


def _simular_resultado(data, idx_entrada, precio_entrada):
    objetivo = precio_entrada * (1 + OBJETIVO_PCT)
    stop = precio_entrada * (1 - STOP_PCT)

    ts_entrada = data.index[idx_entrada]
    fin_absoluto = min(idx_entrada + MAX_VELAS_SIMULACION_ABS, len(data))

    for i in range(idx_entrada + 1, fin_absoluto):
        if data.index[i] - ts_entrada > HORIZONTE_TIEMPO:
            precio_final = float(data.iloc[i - 1]["Close"])
            variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
            return "SIN_RESOLVER", variacion, data.index[i - 1]

        vela = data.iloc[i]
        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_objetivo and toco_stop:
            return "PERDIO", -STOP_PCT * 100, data.index[i]
        if toco_objetivo:
            return "GANO", OBJETIVO_PCT * 100, data.index[i]
        if toco_stop:
            return "PERDIO", -STOP_PCT * 100, data.index[i]

    precio_final = float(data.iloc[fin_absoluto - 1]["Close"])
    variacion = ((precio_final - precio_entrada) / precio_entrada) * 100
    return "SIN_RESOLVER", variacion, data.index[fin_absoluto - 1]


def _calcular_dinero_operacion(variacion_pct):
    """Método exacto pedido: la comisión de entrada sale del desembolso
    total, y la de salida se descuenta de lo recibido al vender."""

    monto_invertido_real = DESEMBOLSO_TOTAL - COMISION  # $4,993,000
    valor_bruto_al_salir = monto_invertido_real * (1 + variacion_pct / 100)
    valor_neto_recibido = valor_bruto_al_salir - COMISION

    resultado_neto = valor_neto_recibido - DESEMBOLSO_TOTAL

    return resultado_neto, valor_neto_recibido


def correr(dias):
    print(f"Desembolso por operación: ${DESEMBOLSO_TOTAL:,.0f} COP")
    print(f"Comisión por lado: ${COMISION:,.0f} COP")
    print(f"Monto real invertido tras comisión de entrada: ${DESEMBOLSO_TOTAL - COMISION:,.0f} COP")
    print(f"Regla de salida: objetivo +{OBJETIVO_PCT*100:.0f}% / stop -{STOP_PCT*100:.0f}% "
          f"/ horizonte {HORIZONTE_TIEMPO.days} días")
    print()

    resultado_total_general = 0.0
    operaciones_total_general = 0

    for symbol in ACTIVOS:
        print("=" * 90)
        print(f"{symbol}")
        print("=" * 90)

        data = _cargar_datos(symbol, dias)
        if data is None or len(data) < MIN_VELAS_PARA_SCORE + 10:
            print("  Sin datos suficientes.")
            print()
            continue

        entradas = _detectar_entradas(data)

        print(f"  Datos recibidos de Yahoo Finance: {data.index[0].strftime('%Y-%m-%d')} "
              f"a {data.index[-1].strftime('%Y-%m-%d')} "
              f"({(data.index[-1] - data.index[0]).days} días, {len(data)} velas)")
        print()

        if not entradas:
            print("  No se detectaron señales (score >= "
                  f"{Settings.UMBRAL_SENAL}) en el período.")
            print()
            continue

        resultado_neto_symbol = 0.0
        ganaron = 0
        perdieron = 0
        sin_resolver = 0

        for entrada in entradas:
            resultado, variacion_pct, fecha_venta = _simular_resultado(data, entrada.idx, entrada.entrada_precio)
            resultado_neto, valor_neto_recibido = _calcular_dinero_operacion(variacion_pct)

            resultado_neto_symbol += resultado_neto

            if resultado == "GANO":
                ganaron += 1
            elif resultado == "PERDIO":
                perdieron += 1
            else:
                sin_resolver += 1

            duracion = fecha_venta - entrada.entrada_ts

            print(
                f"  Compra {entrada.entrada_ts.strftime('%Y-%m-%d %H:%M')} @ ${entrada.entrada_precio:,.2f}  ->  "
                f"Venta {fecha_venta.strftime('%Y-%m-%d %H:%M')} ({duracion})  |  {resultado:12} | "
                f"variación {variacion_pct:+.2f}% | recibido ${valor_neto_recibido:,.0f} | "
                f"neto {resultado_neto:+,.0f} COP"
            )

        print("-" * 90)
        print(f"  Operaciones: {len(entradas)} (GANO={ganaron} PERDIO={perdieron} SIN_RESOLVER={sin_resolver})")
        print(f"  Resultado neto de {symbol}: ${resultado_neto_symbol:+,.0f} COP")
        print()

        resultado_total_general += resultado_neto_symbol
        operaciones_total_general += len(entradas)

    print("=" * 90)
    print(f"RESUMEN GENERAL ({len(ACTIVOS)} acciones juntas)")
    print("=" * 90)
    print(f"Total de operaciones: {operaciones_total_general}")
    print(f"Capital total desembolsado: ${operaciones_total_general * DESEMBOLSO_TOTAL:,.0f} COP")
    print(f"Resultado neto total: ${resultado_total_general:+,.0f} COP")
    print("=" * 90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    args = parser.parse_args()

    correr(args.dias)