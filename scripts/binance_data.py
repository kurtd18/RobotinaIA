"""
Trae velas históricas desde la API pública de Binance (gratis, sin API
key - solo para datos de mercado, no para operar). Pagina
automáticamente para saltar el límite de 1000 velas por solicitud.

Devuelve un DataFrame con columnas Open, High, Low, Close, Volume,
indexado por fecha en UTC - mismo formato que usa yfinance en el resto
del proyecto, para que los scripts de backtest existentes funcionen sin
cambios, solo apuntando a esta función en vez de yf.Ticker(...).history().
"""

from datetime import datetime, timezone
import time

import pandas as pd
import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

INTERVALO_A_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}

MAX_REINTENTOS = 4
TIMEOUT_SEGUNDOS = 30


def _pedir_con_reintentos(params):
    """Pide una página a Binance, reintentando con espera creciente si hay
    una falla de red pasajera (timeout, conexión caída, etc.)."""

    ultimo_error = None

    for intento in range(MAX_REINTENTOS):
        try:
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=TIMEOUT_SEGUNDOS)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            raise  # error del cliente (ej. símbolo no existe) - no reintentar, no se va a arreglar
        except requests.exceptions.RequestException as e:
            ultimo_error = e
            espera = 2 ** intento  # 1, 2, 4, 8 segundos
            print(f"    (falla de red, reintentando en {espera}s... "
                  f"intento {intento + 1}/{MAX_REINTENTOS}: {type(e).__name__})")
            time.sleep(espera)

    raise ultimo_error


def obtener_klines(symbol, interval, fecha_inicio, fecha_fin=None):
    """
    symbol: ej. "BTCUSDT"
    interval: ej. "5m" (ver INTERVALO_A_MS para los intervalos soportados)
    fecha_inicio, fecha_fin: datetime (si no tienen timezone, se asumen UTC)
    """
    if fecha_fin is None:
        fecha_fin = datetime.now(timezone.utc)

    if fecha_inicio.tzinfo is None:
        fecha_inicio = fecha_inicio.replace(tzinfo=timezone.utc)
    if fecha_fin.tzinfo is None:
        fecha_fin = fecha_fin.replace(tzinfo=timezone.utc)

    start_ms = int(fecha_inicio.timestamp() * 1000)
    end_ms = int(fecha_fin.timestamp() * 1000)
    paso_ms = INTERVALO_A_MS.get(interval, 300_000)

    todas_las_velas = []
    cursor = start_ms
    limite_iteraciones = 2000  # seguridad, para nunca quedar en loop infinito

    for _ in range(limite_iteraciones):
        if cursor >= end_ms:
            break

        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        resp = _pedir_con_reintentos(params)
        datos = resp

        if not datos:
            break

        todas_las_velas.extend(datos)

        ultimo_open_time = datos[-1][0]
        siguiente_cursor = ultimo_open_time + paso_ms

        if siguiente_cursor <= cursor:
            # protección extra: si Binance devuelve algo que no avanza el
            # cursor, cortamos en vez de repetir indefinidamente
            break

        cursor = siguiente_cursor

        if len(datos) < 1000:
            # ya llegamos al final de lo disponible
            break

    if not todas_las_velas:
        return None

    df = pd.DataFrame(todas_las_velas, columns=[
        "OpenTime", "Open", "High", "Low", "Close", "Volume",
        "CloseTime", "QuoteAssetVolume", "NumTrades",
        "TakerBuyBase", "TakerBuyQuote", "Ignore",
    ])

    df["OpenTime"] = pd.to_datetime(df["OpenTime"], unit="ms", utc=True)
    df = df.set_index("OpenTime")
    df.index.name = None
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df = df[~df.index.duplicated(keep="first")]
    df = df.sort_index()

    return df