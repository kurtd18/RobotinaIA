"""
Análisis de señales cripto (RSI/MFI/Bollinger%B/SMA200) y notificación
por Telegram.

Reemplaza el paso anterior, que le pedía a un LLM (vía herramientas MCP)
que calculara y redactara estos indicadores en lenguaje natural. Eso
produjo valores distintos para el mismo momento de mercado en corridas
casi simultáneas (ej. RSI de XRP = 66.58 en un mensaje y = 83 en el
siguiente, minutos después) - inaceptable para un sistema que genera
señales de entrada con dinero real.

Aquí el cálculo es 100% determinístico: mismos datos de entrada ->
mismo resultado, siempre. El indicador se calcula sobre las velas
reales de Binance, la regla de entrada se aplica como código, no como
"criterio" de un modelo, y el mensaje se arma con f-strings, no con
texto generado. No hay ningún paso de LLM en esta ruta.

Universo, gatillo de entrada y SL/TP validados en
crypto-alerts/backtest/ (ver backtest_precision_por_moneda.py,
backtest_sondeo_sltp.py y los commits asociados):
  - Universo de 7 monedas seleccionadas por precisión del gatillo (de
    un universo original de 15, se descartaron BTC/BNB/SOL/TRX/BCH/UNI/
    ETH por precisión insuficiente en al menos un lado LARGO/CORTO).
  - El cruce EMA12/26 se eliminó como vía de entrada: medido en 4h sobre
    las 15 monedas, tenía precisión peor que el azar (lift < 1).
  - LARGO exige RSI+MFI+Bollinger%B en sobreventa simultánea (el
    "gatillo triple"), que en backtest da mejor precisión que RSI solo.
    Para CORTO el triple no mejoró sobre RSI solo, así que ese lado
    sigue usando solo RSI.
  - SL 3.5% / TP 1.5% fue la mejor combinación en un sondeo de 81
    combinaciones (SL y TP de 1% a 5%) sobre este universo y gatillo.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas_ta as ta
from loguru import logger

from app.providers.binance_provider import BinanceProvider, BinanceProviderError
from app.providers.yahoo_provider import YahooProvider, YahooProviderError
from app.services.telegram_service import enviar_mensaje_telegram

SIMBOLOS = ["XRP", "ADA", "DOGE", "LINK", "AVAX", "DOT", "LTC"]
INTERVALO = "1h"
VELAS_NECESARIAS = 250  # margen sobre las 200 que pide la SMA200

# La API spot de Binance (api.binance.com) devuelve HTTP 451 (bloqueo
# geográfico) desde runners de GitHub Actions alojados en EE.UU. Yahoo
# Finance no tiene esa restricción, así que sirve como respaldo -
# mismo shape de DataFrame (columna "Close"), solo cambia el símbolo.
SIMBOLO_A_TICKER_YAHOO = {
    "XRP": "XRP-USD",
    "ADA": "ADA-USD",
    "DOGE": "DOGE-USD",
    "LINK": "LINK-USD",
    "AVAX": "AVAX-USD",
    "DOT": "DOT-USD",
    "LTC": "LTC-USD",
}

RSI_PERIODO = 14
MFI_PERIODO = 14
BB_PERIODO = 20
BB_DESV = 2
SMA_TENDENCIA = 200

RSI_SOBREVENTA = 30
RSI_SOBRECOMPRA = 70
MFI_SOBREVENTA = 20

STOP_LOSS_PCT = 0.035
TAKE_PROFIT_PCT = 0.015


def obtener_velas(simbolo: str) -> "pd.DataFrame":
    """
    Velas 1h para `símbolo`, vía Binance primero y Yahoo Finance como
    respaldo si Binance falla (típicamente HTTP 451 en runners de CI
    de EE.UU.). Lanza RuntimeError si ambas fuentes fallan.
    """
    try:
        return BinanceProvider().get_ohlcv(f"{simbolo}USDT", INTERVALO, num_velas=VELAS_NECESARIAS)
    except BinanceProviderError as e_binance:
        logger.warning(f"Binance falló para {simbolo} ({e_binance}), probando Yahoo Finance...")
        try:
            ticker = SIMBOLO_A_TICKER_YAHOO[simbolo]
            return YahooProvider().get_hourly_history(ticker, period="30d")
        except YahooProviderError as e_yahoo:
            raise RuntimeError(
                f"No se pudo obtener velas de {simbolo} ni por Binance ni por Yahoo Finance "
                f"(Binance: {e_binance} | Yahoo: {e_yahoo})"
            ) from e_yahoo


def calcular_indicadores(simbolo: str) -> dict:
    """Descarga velas 1h (Binance con respaldo en Yahoo Finance) y
    calcula RSI/MFI/Bollinger%B/SMA200 con pandas_ta.

    Lanza RuntimeError si no se pudieron obtener datos de ninguna
    fuente (se deja propagar para que quien llame decida si omite esa
    moneda).
    """
    df = obtener_velas(simbolo)

    cierre, alto, bajo, volumen = df["Close"], df["High"], df["Low"], df["Volume"]
    rsi = ta.rsi(cierre, length=RSI_PERIODO)
    mfi = ta.mfi(alto, bajo, cierre, volumen, length=MFI_PERIODO)
    bbands = ta.bbands(cierre, length=BB_PERIODO, std=BB_DESV)
    sma200 = ta.sma(cierre, length=SMA_TENDENCIA)

    if rsi is None or mfi is None or bbands is None or sma200 is None or sma200.dropna().empty:
        raise RuntimeError(
            f"Datos insuficientes para calcular indicadores de {simbolo} "
            f"({len(df)} velas disponibles, se necesitan al menos {SMA_TENDENCIA})"
        )

    bb_lower, bb_upper = bbands.iloc[:, 0], bbands.iloc[:, 2]
    bb_pct_b = (cierre - bb_lower) / (bb_upper - bb_lower)

    precio_actual = float(cierre.iloc[-1])
    rsi_actual = float(rsi.iloc[-1])
    mfi_actual = float(mfi.iloc[-1])
    bb_pct_b_actual = float(bb_pct_b.iloc[-1])
    sma200_actual = float(sma200.iloc[-1])
    tendencia_alcista = precio_actual > sma200_actual

    return {
        "simbolo": simbolo,
        "precio": precio_actual,
        "rsi": rsi_actual,
        "mfi": mfi_actual,
        "bb_pct_b": bb_pct_b_actual,
        "tendencia_alcista": tendencia_alcista,
    }


def evaluar_senal(indicadores: dict) -> dict | None:
    """Aplica la regla de entrada validada por backtesting (730 días,
    universo de 7 monedas, ver docstring del módulo) - sin criterio
    adicional:

    LARGO solo si: precio > SMA200 Y RSI < 30 Y MFI < 20 Y Bollinger%B < 0
    CORTO solo si: precio < SMA200 Y RSI > 70
    """
    precio = indicadores["precio"]
    rsi = indicadores["rsi"]
    mfi = indicadores["mfi"]
    bb_pct_b = indicadores["bb_pct_b"]
    alcista = indicadores["tendencia_alcista"]

    sobreventa_triple = rsi < RSI_SOBREVENTA and mfi < MFI_SOBREVENTA and bb_pct_b < 0
    sobrecompra = rsi > RSI_SOBRECOMPRA

    if alcista and sobreventa_triple:
        return {
            "direccion": "LARGO",
            "precio_entrada": precio,
            "stop_loss": precio * (1 - STOP_LOSS_PCT),
            "take_profit": precio * (1 + TAKE_PROFIT_PCT),
            "razon": "precio sobre SMA200 + RSI/MFI/Bollinger%B en sobreventa simultánea",
        }

    if not alcista and sobrecompra:
        return {
            "direccion": "CORTO",
            "precio_entrada": precio,
            "stop_loss": precio * (1 + STOP_LOSS_PCT),
            "take_profit": precio * (1 - TAKE_PROFIT_PCT),
            "razon": "precio bajo SMA200 + RSI en sobrecompra",
        }

    return None


def armar_tabla(resultados: list[dict]) -> str:
    """Tabla de precio/RSI/tendencia en bloque de código (monoespaciado),
    para que Telegram alinee las columnas de verdad - el Markdown
    "legacy" que usa el bot no soporta tablas, solo texto plano y
    bloques ```pre```, que sí respetan el ancho fijo de cada columna.
    """
    encabezado = f"{'Moneda':<7}{'Precio':>14}{'RSI':>8}  Tendencia"
    filas = [encabezado, "-" * len(encabezado)]
    for r in resultados:
        tendencia = "Arriba" if r["tendencia_alcista"] else "Bajista"
        precio_fmt = f"${r['precio']:,.4f}"
        filas.append(f"{r['simbolo']:<7}{precio_fmt:>14}{r['rsi']:>8.2f}  {tendencia}")
    return "```\n" + "\n".join(filas) + "\n```"


def armar_mensaje(resultados: list[dict], senales: list[dict]) -> str:
    lineas = ["*Crypto Alerts*", ""]

    lineas.append(armar_tabla(resultados))

    lineas.append("")

    if senales:
        lineas.append("*Señales de entrada:*")
        for s in senales:
            lineas.append(
                f"*{s['simbolo']}* - {s['direccion']}\n"
                f"  Entrada: ${s['precio_entrada']:,.4f}\n"
                f"  Stop-loss: ${s['stop_loss']:,.4f}\n"
                f"  Take-profit: ${s['take_profit']:,.4f}\n"
                f"  Razón: {s['razon']}"
            )
    else:
        lineas.append("Sin señales de entrada válidas en este momento.")

    lineas.append("")
    lineas.append(
        "Basado en backtesting de 730 días, sin comisiones/slippage. "
        "No es asesoría financiera."
    )

    return "\n".join(lineas)


def main() -> int:
    resultados = []
    senales = []

    for simbolo in SIMBOLOS:
        try:
            indicadores = calcular_indicadores(simbolo)
        except RuntimeError as e:
            logger.error(f"Omitiendo {simbolo}: {e}")
            continue

        resultados.append(indicadores)

        senal = evaluar_senal(indicadores)
        if senal:
            senal["simbolo"] = simbolo
            senales.append(senal)

    if not resultados:
        logger.error("No se pudo calcular indicadores para ninguna moneda, no se envía mensaje")
        return 1

    mensaje = armar_mensaje(resultados, senales)
    status = enviar_mensaje_telegram(mensaje, parse_mode="Markdown")

    if status != 200:
        logger.error(f"Fallo al enviar mensaje de Telegram (status={status})")
        return 1

    logger.info("Mensaje de Crypto Alerts enviado correctamente")
    return 0


if __name__ == "__main__":
    sys.exit(main())
