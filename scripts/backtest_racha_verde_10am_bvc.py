"""
Backtest de la estrategia "racha verde" para las 10 acciones BVC, con
ENTRADA RETRASADA Y CONFIRMADA A LAS 10:00AM (en vez de comprar el mismo
día que confirma rojo->verde).

Lógica de entrada:
  1. Día A cierra en rojo (cierre < cierre del día anterior)
  2. Día B (el siguiente día de trading) cierra en verde (cierre > cierre
     del día A) -> esto CONFIRMA la señal, pero todavía NO se compra
  3. Día C (el siguiente día de trading después de B), a las 10:00am, se
     revisa el precio: si es >= al cierre del día B, SE COMPRA en ese
     momento. Si es menor, la señal se descarta (no se compra).

Debido al límite de 60 días de Yahoo Finance para datos intradía
(necesarios para saber el precio real a las 10am), este backtest cubre
solo los últimos 60 días, no desde enero como los anteriores.

Salida: mismo trailing stop real (stop inicial -1.5%, objetivo inicial
+3%, incrementos de +1%), simulado sobre velas de 5 minutos.

Dinero: mismo método validado (desembolso $5,000,000 COP, comisión
$7,000 COP por lado, descontada del desembolso/lo recibido al vender).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_racha_verde_10am_bvc.py
    python scripts/backtest_racha_verde_10am_bvc.py --dias 59
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TZ_BOGOTA = ZoneInfo("America/Bogota")
HORA_REVISION = dt_time(10, 0)

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

STOP_INICIAL_PCT = 0.015
OBJETIVO_INICIAL_PCT = 0.03
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _cargar_datos_intradia(symbol, dias):
    data = yf.Ticker(symbol).history(period=f"{dias}d", interval="5m")
    if data.empty:
        return None
    data.index = data.index.tz_convert(TZ_BOGOTA)
    return data


def _cierres_diarios(data):
    """A partir de datos intradía, arma un dict {fecha: cierre} con el
    último precio de cada día de trading."""

    fechas_unicas = sorted(set(data.index.date))
    cierres = {}
    for fecha in fechas_unicas:
        velas_del_dia = data[data.index.date == fecha]
        cierres[fecha] = float(velas_del_dia["Close"].iloc[-1])
    return fechas_unicas, cierres


def _buscar_vela_a_las_10am(data, fecha):
    """Busca la primera vela de 5 minutos disponible a partir de las
    10:00am de una fecha dada. Devuelve (timestamp, precio) o None."""

    velas_del_dia = data[data.index.date == fecha]
    if velas_del_dia.empty:
        return None

    velas_desde_10am = velas_del_dia[velas_del_dia.index.time >= HORA_REVISION]
    if velas_desde_10am.empty:
        return None

    ts = velas_desde_10am.index[0]
    precio = float(velas_desde_10am["Close"].iloc[0])
    return ts, precio


def _simular_trailing_stop(data, idx_entrada, entrada_precio):
    """Mismo trailing stop real de siempre, pero recorriendo velas de 5
    minutos en vez de días - misma lógica, más precisión."""

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
    fecha_rojo: object
    fecha_verde: object
    cierre_verde: float
    entrada_fecha: object
    entrada_precio: float
    salida_fecha: object
    salida_precio: float
    resultado: str
    variacion_pct: float


def _analizar_symbol(data):
    fechas, cierres = _cierres_diarios(data)

    operaciones = []
    en_posicion_hasta_idx = -1

    for k in range(1, len(fechas) - 2):
        fecha_anterior = fechas[k - 1]
        fecha_A = fechas[k]

        es_rojo = cierres[fecha_A] < cierres[fecha_anterior]
        if not es_rojo:
            continue

        fecha_B = fechas[k + 1]
        es_verde = cierres[fecha_B] > cierres[fecha_A]
        if not es_verde:
            continue

        fecha_C = fechas[k + 2]

        resultado_10am = _buscar_vela_a_las_10am(data, fecha_C)
        if resultado_10am is None:
            continue

        ts_10am, precio_10am = resultado_10am

        if precio_10am < cierres[fecha_B]:
            continue  # no se confirma la compra

        idx_entrada = data.index.get_loc(ts_10am)
        if isinstance(idx_entrada, slice):
            idx_entrada = idx_entrada.start

        if idx_entrada <= en_posicion_hasta_idx:
            continue  # ya hay una posición abierta en ese momento

        entrada_precio = precio_10am
        entrada_fecha = ts_10am

        resultado, salida_precio, salida_fecha = _simular_trailing_stop(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100

        operaciones.append(Operacion(
            fecha_rojo=fecha_A, fecha_verde=fecha_B, cierre_verde=cierres[fecha_B],
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


def correr(dias):
    print(f"Desembolso por operación: ${DESEMBOLSO_TOTAL:,.0f} COP | Comisión por lado: ${COMISION:,.0f} COP")
    print(f"Entrada: confirmada a las 10:00am del día C (2 días después del rojo), "
          f"solo si el precio sigue >= al cierre verde")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}% inicial, "
          f"+{OBJETIVO_INICIAL_PCT*100:.0f}% objetivo inicial, +{INCREMENTO_PCT*100:.0f}% incrementos)")
    print()

    neto_total_general = 0.0
    operaciones_total_general = 0
    ganadoras_general = 0
    perdedoras_general = 0

    for symbol in ACTIVOS:
        print("=" * 100)
        print(symbol)
        print("=" * 100)

        data = _cargar_datos_intradia(symbol, dias)
        if data is None or len(data) < 100:
            print("  Sin datos suficientes.")
            print()
            continue

        print(f"  Rango: {data.index[0].strftime('%Y-%m-%d')} a {data.index[-1].strftime('%Y-%m-%d')} "
              f"({len(data)} velas)")

        operaciones = _analizar_symbol(data)

        if not operaciones:
            print("  No se generaron operaciones (ninguna señal confirmó precio >= cierre verde a las 10am).")
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

            print(f"  Rojo {op.fecha_rojo} | Verde {op.fecha_verde} (cierre ${op.cierre_verde:,.2f}) | "
                  f"Entrada {op.entrada_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.entrada_precio:,.2f} -> "
                  f"Salida {op.salida_fecha.strftime('%Y-%m-%d %H:%M')} @ ${op.salida_precio:,.2f} | "
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
        print("⚠️  Muestra menor a 30 operaciones - no es suficiente para conclusiones firmes "
              "(esperado, al reducir a 60 días).")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=59)
    args = parser.parse_args()

    correr(args.dias)
    