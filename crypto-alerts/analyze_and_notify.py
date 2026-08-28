"""
Analisis de senales cripto (RSI/EMA/SMA200) y notificacion por Telegram.

Reemplaza el paso anterior, que le pedia a un LLM (via herramientas MCP)
que calculara y redactara estos indicadores en lenguaje natural. Eso
produjo valores distintos para el mismo momento de mercado en corridas
casi simultaneas (ej. RSI de XRP = 66.58 en un mensaje y = 83 en el
siguiente, minutos despues) - inaceptable para un sistema que genera
senales de entrada con dinero real.

Aqui el calculo es 100% deterministico: mismos datos de entrada ->
mismo resultado, siempre. pandas_ta calcula RSI/EMA/SMA sobre las velas
reales de Binance, la regla de entrada (ya validada por backtesting) se
aplica como codigo, no como "criterio" de un modelo, y el mensaje se
arma con f-strings, no con texto generado. No hay ningun paso de LLM en
esta ruta.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas_ta as ta
from loguru import logger

from app.providers.binance_provider import BinanceProvider, BinanceProviderError
from app.services.telegram_service import enviar_mensaje_telegram

SIMBOLOS = ["XRP", "ETH", "DOGE", "SOL"]
INTERVALO = "1h"
VELAS_NECESARIAS = 250  # margen sobre las 200 que pide la SMA200

RSI_PERIODO = 14
EMA_RAPIDA = 12
EMA_LENTA = 26
SMA_TENDENCIA = 200

RSI_SOBREVENTA = 30
RSI_SOBRECOMPRA = 70
VELAS_CRUCE_RECIENTE = 3

STOP_LOSS_PCT = 0.05
TAKE_PROFIT_PCT = 0.03


def calcular_indicadores(simbolo: str) -> dict:
    """Descarga velas 1h de Binance y calcula RSI/EMA/SMA200 con pandas_ta.

    Lanza BinanceProviderError si no se pudieron obtener datos (se deja
    propagar para que el llamador decida si omite esa moneda).
    """
    provider = BinanceProvider()
    df = provider.get_ohlcv(f"{simbolo}USDT", INTERVALO, num_velas=VELAS_NECESARIAS)

    cierre = df["Close"]
    rsi = ta.rsi(cierre, length=RSI_PERIODO)
    ema_rapida = ta.ema(cierre, length=EMA_RAPIDA)
    ema_lenta = ta.ema(cierre, length=EMA_LENTA)
    sma200 = ta.sma(cierre, length=SMA_TENDENCIA)

    if rsi is None or sma200 is None or sma200.dropna().empty:
        raise BinanceProviderError(
            f"Datos insuficientes para calcular indicadores de {simbolo} "
            f"({len(df)} velas disponibles, se necesitan al menos {SMA_TENDENCIA})"
        )

    precio_actual = float(cierre.iloc[-1])
    rsi_actual = float(rsi.iloc[-1])
    sma200_actual = float(sma200.iloc[-1])
    tendencia_alcista = precio_actual > sma200_actual

    diff_ema = ema_rapida - ema_lenta
    cruce = None  # None, "dorado" o "muerte"
    for i in range(-VELAS_CRUCE_RECIENTE, 0):
        anterior, actual = diff_ema.iloc[i - 1], diff_ema.iloc[i]
        if pd_isna(anterior) or pd_isna(actual):
            continue
        if anterior < 0 and actual > 0:
            cruce = "dorado"
        elif anterior > 0 and actual < 0:
            cruce = "muerte"

    return {
        "simbolo": simbolo,
        "precio": precio_actual,
        "rsi": rsi_actual,
        "tendencia_alcista": tendencia_alcista,
        "cruce_reciente": cruce,
    }


def pd_isna(valor) -> bool:
    import math
    return valor is None or (isinstance(valor, float) and math.isnan(valor))


def evaluar_senal(indicadores: dict) -> dict | None:
    """Aplica la regla de entrada validada por backtesting (360 dias),
    exactamente como esta documentada - sin criterio adicional:

    LARGO solo si: precio > SMA200 Y (RSI < 30 O cruce dorado reciente)
    CORTO solo si: precio < SMA200 Y (RSI > 70 O cruce de la muerte reciente)
    """
    precio = indicadores["precio"]
    rsi = indicadores["rsi"]
    alcista = indicadores["tendencia_alcista"]
    cruce = indicadores["cruce_reciente"]

    if alcista and (rsi < RSI_SOBREVENTA or cruce == "dorado"):
        razon = "precio sobre SMA200"
        razon += " + RSI en sobreventa" if rsi < RSI_SOBREVENTA else ""
        razon += " + cruce dorado reciente" if cruce == "dorado" else ""
        return {
            "direccion": "LARGO",
            "precio_entrada": precio,
            "stop_loss": precio * (1 - STOP_LOSS_PCT),
            "take_profit": precio * (1 + TAKE_PROFIT_PCT),
            "razon": razon,
        }

    if not alcista and (rsi > RSI_SOBRECOMPRA or cruce == "muerte"):
        razon = "precio bajo SMA200"
        razon += " + RSI en sobrecompra" if rsi > RSI_SOBRECOMPRA else ""
        razon += " + cruce de la muerte reciente" if cruce == "muerte" else ""
        return {
            "direccion": "CORTO",
            "precio_entrada": precio,
            "stop_loss": precio * (1 + STOP_LOSS_PCT),
            "take_profit": precio * (1 - TAKE_PROFIT_PCT),
            "razon": razon,
        }

    return None


def armar_mensaje(resultados: list[dict], senales: list[dict]) -> str:
    lineas = ["*Crypto Alerts*", ""]

    lineas.append("Precio | RSI | Tendencia")
    for r in resultados:
        tendencia = "Arriba" if r["tendencia_alcista"] else "Bajista"
        lineas.append(f"*{r['simbolo']}*: ${r['precio']:,.4f} | RSI {r['rsi']:.2f} | {tendencia}")

    lineas.append("")

    if senales:
        lineas.append("*Senales de entrada:*")
        for s in senales:
            lineas.append(
                f"*{s['simbolo']}* - {s['direccion']}\n"
                f"  Entrada: ${s['precio_entrada']:,.4f}\n"
                f"  Stop-loss: ${s['stop_loss']:,.4f}\n"
                f"  Take-profit: ${s['take_profit']:,.4f}\n"
                f"  Razon: {s['razon']}"
            )
    else:
        lineas.append("Sin senales de entrada validas en este momento.")

    lineas.append("")
    lineas.append(
        "Basado en backtesting de 360 dias, sin comisiones/slippage. "
        "No es asesoria financiera."
    )

    return "\n".join(lineas)


def main() -> int:
    resultados = []
    senales = []

    for simbolo in SIMBOLOS:
        try:
            indicadores = calcular_indicadores(simbolo)
        except BinanceProviderError as e:
            logger.error(f"Omitiendo {simbolo}: {e}")
            continue

        resultados.append(indicadores)

        senal = evaluar_senal(indicadores)
        if senal:
            senal["simbolo"] = simbolo
            senales.append(senal)

    if not resultados:
        logger.error("No se pudo calcular indicadores para ninguna moneda, no se envia mensaje")
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
