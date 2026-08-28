"""
Simula cómo se hubiera comportado la revisión cada 30 minutos (8am-5pm)
en un día reciente real - reutiliza directamente las funciones de
app/strategies/rsi2_connors.py (las mismas que corren en producción), no
una copia aparte, para garantizar que el comportamiento simulado sea
idéntico al real.

Para cada snapshot de 30 minutos dentro del horario de mercado, reconstruye
lo que el sistema hubiera "visto" en ese momento: el historial diario
hasta AYER, más el precio de ESE momento como si fuera el cierre de "hoy"
todavía en formación - y revisa si con eso se hubiera disparado una
señal de entrada o salida.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/simular_revision_intradia.py
    python scripts/simular_revision_intradia.py --activos ECOPETROL.CL,NUTRESA.CL
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.strategies.rsi2_connors import (
    ACTIVOS, SMA_PERIODO, RSI_ENTRADA, RSI_SALIDA,
    _limpiar_datos, _calcular_indicadores, _hubo_cruce_entrada_hoy, _hubo_condicion_salida_hoy,
)

TZ_BOGOTA = ZoneInfo("America/Bogota")
HORA_INICIO = "08:00"
HORA_FIN = "17:00"


def _obtener_snapshots_intradia(symbol, intervalo):
    """Descarga velas del intervalo indicado del último día de trading
    disponible, para usarlas como los "momentos" que se hubieran
    revisado."""

    try:
        data_intradia = yf.Ticker(symbol).history(period="5d", interval=intervalo)
    except Exception:
        return None

    if data_intradia.empty:
        return None

    if data_intradia.index.tz is not None:
        data_intradia.index = data_intradia.index.tz_convert(TZ_BOGOTA)

    ultimo_dia = data_intradia.index[-1].date()
    data_ultimo_dia = data_intradia[data_intradia.index.date == ultimo_dia]

    data_ultimo_dia = data_ultimo_dia[
        (data_ultimo_dia.index.strftime("%H:%M") >= HORA_INICIO)
        & (data_ultimo_dia.index.strftime("%H:%M") <= HORA_FIN)
    ]

    return data_ultimo_dia


def _simular_activo(symbol, intervalo):
    try:
        data_diaria = yf.Ticker(symbol).history(period="2y", interval="1d")
    except Exception as e:
        print(f"{symbol}: error descargando datos diarios ({type(e).__name__})")
        return

    if data_diaria is None or data_diaria.empty:
        print(f"{symbol}: sin datos diarios")
        return

    data_diaria = _limpiar_datos(data_diaria)
    if len(data_diaria) < SMA_PERIODO + 5:
        print(f"{symbol}: sin datos diarios suficientes")
        return

    # El historial diario hasta AYER (sin el día de hoy, que vamos a
    # reconstruir nosotros con cada snapshot intradía)
    ultimo_dia_diario = data_diaria.index[-1].date()
    data_hasta_ayer = data_diaria[data_diaria.index.date < ultimo_dia_diario]

    snapshots = _obtener_snapshots_intradia(symbol, intervalo)
    if snapshots is None or snapshots.empty:
        print(f"{symbol}: sin snapshots intradía")
        return

    print(f"=== {symbol} ===")
    print(f"  (día simulado: {snapshots.index[0].date()}, {len(snapshots)} snapshots de 30 min)")

    en_posicion_simulada = False

    for hora_snapshot, fila in snapshots.iterrows():
        precio_snapshot = float(fila["Close"])

        # Reconstruir la vela de "hoy todavía en formación": mismo Open
        # del día, pero High/Low/Close ajustados al precio de este
        # snapshot específico (lo más fiel posible a lo que produciría
        # yfinance con interval="1d" en ese momento del día).
        fila_hoy_simulada = pd.DataFrame({
            "Open": [precio_snapshot], "High": [precio_snapshot], "Low": [precio_snapshot],
            "Close": [precio_snapshot], "Volume": [1],
        }, index=[pd.Timestamp(hora_snapshot.date())])

        data_simulada = pd.concat([data_hasta_ayer, fila_hoy_simulada])

        rsi, sma = _calcular_indicadores(data_simulada)
        if rsi is None:
            continue

        rsi_valor = float(rsi.iloc[-1]) if rsi.iloc[-1] == rsi.iloc[-1] else None
        sma_valor = float(sma.iloc[-1]) if sma.iloc[-1] == sma.iloc[-1] else None

        if not en_posicion_simulada:
            hubo_entrada = _hubo_cruce_entrada_hoy(data_simulada, rsi, sma)
            marca = "🟢 ENTRADA" if hubo_entrada else ""
            if hubo_entrada:
                en_posicion_simulada = True
        else:
            hubo_salida = _hubo_condicion_salida_hoy(data_simulada, rsi, sma)
            marca = "🔴 SALIDA" if hubo_salida else ""
            if hubo_salida:
                en_posicion_simulada = False

        print(f"  {hora_snapshot.strftime('%H:%M')} | precio={precio_snapshot:,.2f} | "
              f"RSI2={rsi_valor:.2f} | SMA{SMA_PERIODO}={sma_valor:,.2f} | {marca}")

    print()


def correr(activos, intervalo):
    print(f"Simulación de revisión cada {intervalo} ({HORA_INICIO} a {HORA_FIN}), {len(activos)} activos")
    print("(usa las mismas funciones de app/strategies/rsi2_connors.py que corren en producción)")
    print()

    for symbol in activos:
        try:
            _simular_activo(symbol, intervalo)
        except Exception as e:
            print(f"{symbol}: error inesperado ({type(e).__name__}: {e})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activos", type=str, default=None,
                         help="Lista separada por comas. Por defecto usa las 10 acciones BVC.")
    parser.add_argument("--intervalo", type=str, default="1h",
                         help="Intervalo de las velas intradía a simular (ej. 30m, 1h)")
    args = parser.parse_args()

    if args.activos:
        activos = args.activos.split(",")
    else:
        activos = [
            "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
            "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
        ]

    correr(activos, args.intervalo)