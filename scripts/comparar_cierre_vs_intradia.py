"""
Compara el resultado en dinero de la estrategia RSI(2) de Connors medida
de 2 formas distintas, sobre los últimos 120 días, en las 10 acciones
BVC:

  1. SOLO AL CIERRE: la señal se revisa una vez al día, con el cierre ya
     confirmado (como en el backtest de 8 años ya validado).
  2. CADA HORA: la señal se revisa cada hora dentro del horario de
     mercado, usando el precio en vivo de ese momento como si fuera el
     cierre de "hoy" todavía en formación - la misma reconstrucción que
     usamos en simular_revision_intradia.py, pero encadenada día tras
     día para armar operaciones completas con entrada y salida reales.

Reutiliza las funciones ya validadas de app/strategies/rsi2_connors.py
para la detección de entrada/salida - la única diferencia entre los 2
métodos es EN QUÉ MOMENTOS se revisa la condición, no la lógica en sí.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/comparar_cierre_vs_intradia.py
    python scripts/comparar_cierre_vs_intradia.py --dias 120
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.strategies.rsi2_connors import (
    SMA_PERIODO, _limpiar_datos, _calcular_indicadores,
    _hubo_cruce_entrada_hoy, _hubo_condicion_salida_hoy,
)

ACTIVOS = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

TZ_BOGOTA = ZoneInfo("America/Bogota")
HORA_INICIO = "08:00"
HORA_FIN = "17:00"

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


@dataclass
class Operacion:
    entrada_fecha: object
    entrada_precio: float
    salida_fecha: object
    salida_precio: float
    variacion_pct: float
    neto: float


def _backtest_solo_cierre(data_diaria, fecha_inicio_ventana):
    """Revisión una vez al día, con el cierre confirmado - misma lógica
    que backtest_rsi2_connors.py, restringida a la ventana de prueba."""

    operaciones = []
    en_posicion = False
    entrada_fecha = entrada_precio = None

    indices_ventana = [i for i in range(len(data_diaria)) if data_diaria.index[i].date() >= fecha_inicio_ventana]

    for i in indices_ventana:
        if i < SMA_PERIODO + 2:
            continue

        data_hasta_hoy = data_diaria.iloc[: i + 1]
        rsi, sma = _calcular_indicadores(data_hasta_hoy)
        if rsi is None:
            continue

        precio_hoy = float(data_diaria["Close"].iloc[i])
        fecha_hoy = data_diaria.index[i]

        if not en_posicion:
            if _hubo_cruce_entrada_hoy(data_hasta_hoy, rsi, sma):
                en_posicion = True
                entrada_fecha, entrada_precio = fecha_hoy, precio_hoy
        else:
            if _hubo_condicion_salida_hoy(data_hasta_hoy, rsi, sma):
                variacion_pct = ((precio_hoy - entrada_precio) / entrada_precio) * 100
                operaciones.append(Operacion(
                    entrada_fecha, entrada_precio, fecha_hoy, precio_hoy,
                    variacion_pct, _calcular_dinero(variacion_pct),
                ))
                en_posicion = False

    return operaciones


def _backtest_cada_hora(data_diaria, data_horaria, fecha_inicio_ventana):
    """Revisión cada hora dentro del horario de mercado, reconstruyendo
    la vela de 'hoy en formación' con el precio de cada hora."""

    operaciones = []
    en_posicion = False
    entrada_fecha = entrada_precio = None

    data_horaria = data_horaria[
        (data_horaria.index.strftime("%H:%M") >= HORA_INICIO)
        & (data_horaria.index.strftime("%H:%M") <= HORA_FIN)
    ]

    dias_de_prueba = sorted(set(d.date() for d in data_horaria.index if d.date() >= fecha_inicio_ventana))

    for dia in dias_de_prueba:
        data_hasta_ayer = data_diaria[data_diaria.index.date < dia]
        if len(data_hasta_ayer) < SMA_PERIODO + 2:
            continue

        horas_del_dia = data_horaria[data_horaria.index.date == dia]

        for hora_snapshot, fila in horas_del_dia.iterrows():
            precio_snapshot = float(fila["Close"])

            fila_hoy = pd.DataFrame({
                "Open": [precio_snapshot], "High": [precio_snapshot], "Low": [precio_snapshot],
                "Close": [precio_snapshot], "Volume": [1],
            }, index=[pd.Timestamp(dia)])

            data_simulada = pd.concat([data_hasta_ayer, fila_hoy])
            rsi, sma = _calcular_indicadores(data_simulada)
            if rsi is None:
                continue

            if not en_posicion:
                if _hubo_cruce_entrada_hoy(data_simulada, rsi, sma):
                    en_posicion = True
                    entrada_fecha, entrada_precio = hora_snapshot, precio_snapshot
            else:
                if _hubo_condicion_salida_hoy(data_simulada, rsi, sma):
                    variacion_pct = ((precio_snapshot - entrada_precio) / entrada_precio) * 100
                    operaciones.append(Operacion(
                        entrada_fecha, entrada_precio, hora_snapshot, precio_snapshot,
                        variacion_pct, _calcular_dinero(variacion_pct),
                    ))
                    en_posicion = False

    return operaciones


def _procesar_activo(symbol, dias):
    try:
        data_diaria = yf.Ticker(symbol).history(period="2y", interval="1d")
    except Exception as e:
        print(f"{symbol}: error datos diarios ({type(e).__name__})")
        return None, None

    if data_diaria is None or data_diaria.empty:
        print(f"{symbol}: sin datos diarios")
        return None, None

    data_diaria = _limpiar_datos(data_diaria)
    if len(data_diaria) < SMA_PERIODO + 30:
        print(f"{symbol}: datos diarios insuficientes")
        return None, None

    fecha_inicio_ventana = (datetime.now(TZ_BOGOTA) - timedelta(days=dias)).date()

    fecha_inicio_horaria = datetime.now(TZ_BOGOTA) - timedelta(days=dias)
    try:
        data_horaria = yf.Ticker(symbol).history(start=fecha_inicio_horaria, interval="1h")
    except Exception as e:
        print(f"{symbol}: error datos horarios ({type(e).__name__})")
        return None, None

    if data_horaria is None or data_horaria.empty:
        print(f"{symbol}: sin datos horarios")
        return None, None

    if data_horaria.index.tz is not None:
        data_horaria.index = data_horaria.index.tz_convert(TZ_BOGOTA)
    data_horaria = _limpiar_datos(data_horaria)

    ops_cierre = _backtest_solo_cierre(data_diaria, fecha_inicio_ventana)
    ops_hora = _backtest_cada_hora(data_diaria, data_horaria, fecha_inicio_ventana)

    return ops_cierre, ops_hora


def correr(dias):
    print(f"Comparación SOLO AL CIERRE vs CADA HORA - últimos {dias} días, {len(ACTIVOS)} activos")
    print()

    todas_ops_cierre = []
    todas_ops_hora = []

    for symbol in ACTIVOS:
        ops_cierre, ops_hora = _procesar_activo(symbol, dias)
        if ops_cierre is None:
            continue

        neto_cierre = sum(op.neto for op in ops_cierre)
        neto_hora = sum(op.neto for op in ops_hora)

        print(f"{symbol:14} SOLO CIERRE: {len(ops_cierre):2} ops, ${neto_cierre:+,.0f} COP | "
              f"CADA HORA: {len(ops_hora):2} ops, ${neto_hora:+,.0f} COP")

        todas_ops_cierre.extend(ops_cierre)
        todas_ops_hora.extend(ops_hora)

    print()
    print("=" * 100)
    print("RESUMEN")
    print("=" * 100)

    neto_total_cierre = sum(op.neto for op in todas_ops_cierre)
    ganaron_cierre = sum(1 for op in todas_ops_cierre if op.neto > 0)
    print(f"SOLO AL CIERRE: {len(todas_ops_cierre)} operaciones | neto ${neto_total_cierre:+,.0f} COP | "
          f"ganadoras {ganaron_cierre}/{len(todas_ops_cierre) or 1} "
          f"({ganaron_cierre/len(todas_ops_cierre)*100 if todas_ops_cierre else 0:.1f}%)")

    neto_total_hora = sum(op.neto for op in todas_ops_hora)
    ganaron_hora = sum(1 for op in todas_ops_hora if op.neto > 0)
    print(f"CADA HORA:      {len(todas_ops_hora)} operaciones | neto ${neto_total_hora:+,.0f} COP | "
          f"ganadoras {ganaron_hora}/{len(todas_ops_hora) or 1} "
          f"({ganaron_hora/len(todas_ops_hora)*100 if todas_ops_hora else 0:.1f}%)")

    print("=" * 100)
    if len(todas_ops_cierre) < 30 or len(todas_ops_hora) < 30:
        print("⚠️  Alguna de las 2 muestras está por debajo de 30 operaciones - resultado indicativo, no concluyente.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=120)
    args = parser.parse_args()

    correr(args.dias)