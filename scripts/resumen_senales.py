"""
Compara las señales generadas en una ventana de tiempo contra el precio
actual, y envía un resumen por Telegram con el % de variación de cada una.

Uso:
    python scripts/resumen_senales.py                  -> hoy, 09:00 a 10:00
    python scripts/resumen_senales.py 09:00 10:00       -> hoy, rango custom
    python scripts/resumen_senales.py 2026-07-28 09:00 10:00
"""

import sys
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.connection import get_connection
from app.services.telegram_service import enviar_mensaje_telegram

TZ_BOGOTA = ZoneInfo("America/Bogota")


def _parsear_argumentos():
    args = sys.argv[1:]

    hoy = datetime.now(TZ_BOGOTA).date()

    if len(args) == 0:
        fecha, hora_inicio, hora_fin = hoy, dt_time(9, 0), dt_time(10, 0)
    elif len(args) == 2:
        fecha = hoy
        hora_inicio = dt_time.fromisoformat(args[0])
        hora_fin = dt_time.fromisoformat(args[1])
    elif len(args) == 3:
        fecha = datetime.strptime(args[0], "%Y-%m-%d").date()
        hora_inicio = dt_time.fromisoformat(args[1])
        hora_fin = dt_time.fromisoformat(args[2])
    else:
        print("Uso: python scripts/resumen_senales.py [FECHA] HORA_INICIO HORA_FIN")
        sys.exit(1)

    inicio = datetime.combine(fecha, hora_inicio, tzinfo=TZ_BOGOTA)
    fin = datetime.combine(fecha, hora_fin, tzinfo=TZ_BOGOTA)

    return inicio, fin


def _obtener_senales(inicio, fin):
    """Trae señales de la BD cuyo timestamp cae en el rango [inicio, fin)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, symbol, score, price, timestamp
        FROM signals
        ORDER BY id
        """
    )
    filas = cursor.fetchall()
    conn.close()

    resultado = []
    for signal_id, symbol, score, price, timestamp_str in filas:
        ts = _parsear_timestamp(timestamp_str)
        if ts is not None and inicio <= ts < fin:
            resultado.append((signal_id, symbol, score, price, ts))

    return resultado


def _parsear_timestamp(timestamp_str):
    formatos = (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formatos:
        try:
            dt = datetime.strptime(timestamp_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_BOGOTA)
            return dt
        except ValueError:
            continue
    return None


def _precio_actual(symbol):
    data = yf.Ticker(symbol).history(period="1d", interval="5m")
    if data.empty:
        return None
    return float(data.iloc[-1]["Close"])


def generar_resumen(inicio, fin):
    senales = _obtener_senales(inicio, fin)

    if not senales:
        mensaje = (
            f"📊 RESUMEN DE SEÑALES\n\n"
            f"No hubo señales entre {inicio.strftime('%H:%M')} y {fin.strftime('%H:%M')} "
            f"del {inicio.strftime('%Y-%m-%d')}."
        )
        return mensaje

    lineas = [
        f"📊 RESUMEN DE SEÑALES",
        f"{inicio.strftime('%Y-%m-%d')} {inicio.strftime('%H:%M')} - {fin.strftime('%H:%M')}",
        f"Comparado contra precio actual ({datetime.now(TZ_BOGOTA).strftime('%H:%M')})",
        "",
    ]

    for signal_id, symbol, score, precio_senal, ts in senales:
        precio_actual = _precio_actual(symbol)

        if precio_actual is None:
            lineas.append(f"{symbol:15} sin datos actuales")
            continue

        variacion_pct = ((precio_actual - precio_senal) / precio_senal) * 100
        emoji = "🟢" if variacion_pct >= 0 else "🔴"

        lineas.append(
            f"{emoji} {symbol:15} score {score:3} | "
            f"{precio_senal:,.2f} -> {precio_actual:,.2f} | {variacion_pct:+.2f}%"
        )

    return "\n".join(lineas)


if __name__ == "__main__":
    inicio, fin = _parsear_argumentos()
    mensaje = generar_resumen(inicio, fin)

    print(mensaje)
    print()

    codigo = enviar_mensaje_telegram(mensaje)
    print(f"Enviado a Telegram (status {codigo})")