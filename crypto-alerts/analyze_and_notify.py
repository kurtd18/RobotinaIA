"""
Análisis de señales cripto (patrón de flip de vela diaria + RSI/
Estocástico/Williams%R) y notificación por Telegram.

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

Estrategia validada en crypto-alerts/backtest/ (ver
analisis_patron_flip_velas.py y backtest_flip_velas_portafolio.py) -
reemplaza a la anterior (RSI+MFI+Bollinger%B en velas 1h) tras
comparar ambas con capital y comisiones reales sobre 730 días:

  - Velas DIARIAS (antes 1h) - el patrón es de "flip de color de vela":
    una vela roja seguida de una verde (o viceversa), con una condición
    de momentum extremo el día del flip.
  - LARGO: la vela de hoy cierra verde, la de ayer cerró roja, Y el RSI
    de hoy < 30 (58.1% de precisión sobre un movimiento >=5% en <=3
    días, contra una tasa base de 40.0% sin ese filtro).
  - CORTO: la vela de hoy cierra roja, la de ayer cerró verde, Y el
    Estocástico(14) de hoy > 80 Y el Williams%R(14) de hoy > -20 (85.4%
    de precisión sobre un movimiento >=3% en <=5 días, contra una tasa
    base de 70.9%).
  - SL 3% / TP 5% fue la combinación con mejor resultado en backtest de
    portafolio (78 trades, 46.2% win rate, +2.33% neto con comisiones,
    sobre las 7 monedas originales).

Universo ampliado a 15 monedas (de un candidato de 20, ver
analisis_precision_flip_por_moneda.py): las 7 originales (XRP, ADA,
DOGE, LINK, AVAX, DOT, LTC) + 8 nuevas con al menos 5 activaciones
históricas y precisión por encima de la tasa base en al menos un lado
(SOL, UNI, ARB, BCH, APT, OP, ETC, NEAR). Quedaron fuera BTC, ETH, BNB,
TRX, ATOM - muestra grande y confiable, pero precisión que NO supera la
base (no es falta de datos: el patrón no funciona bien ahí). Con las 15
monedas el backtest de portafolio dio +1.29% neto (181 trades, 40.9%
win rate) - menos eficiente por moneda que con las 7 originales, pero
sigue siendo positivo.

El cron corre cada 4h (no una vez al día, por pedido explícito): la
regla lee la vela DIARIA, así que la mayor parte del día se evalúa la
vela de hoy todavía en formación (no cerrada) - el dato solo queda
"confirmado" en la corrida de después de medianoche UTC. Es un
trade-off conocido y aceptado a cambio de notificaciones más
frecuentes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas_ta as ta
from loguru import logger

from app.providers.binance_provider import BinanceProvider, BinanceProviderError
from app.providers.yahoo_provider import YahooProvider, YahooProviderError
from app.services.telegram_service import enviar_mensaje_telegram

SIMBOLOS = ["XRP", "ADA", "DOGE", "LINK", "AVAX", "DOT", "LTC",
            "SOL", "UNI", "ARB", "BCH", "APT", "OP", "ETC", "NEAR"]
INTERVALO = "1d"
VELAS_NECESARIAS = 260  # margen sobre las ~250 que conviene tener para RSI/Estocástico/Williams%R con historia de sobra

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
    "SOL": "SOL-USD",
    "UNI": "UNI-USD",
    "ARB": "ARB-USD",
    "BCH": "BCH-USD",
    "APT": "APT-USD",
    "OP": "OP-USD",
    "ETC": "ETC-USD",
    "NEAR": "NEAR-USD",
}

RSI_PERIODO = 14
STOCH_K, STOCH_D, STOCH_SUAVIZADO = 14, 3, 3
WILLR_PERIODO = 14

RSI_SOBREVENTA_GATILLO = 30
STOCH_SOBRECOMPRA_GATILLO = 80
WILLR_SOBRECOMPRA_GATILLO = -20

STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.05


def obtener_velas(simbolo: str) -> "pd.DataFrame":
    """
    Velas 1D para `símbolo`, vía Binance primero y Yahoo Finance como
    respaldo si Binance falla (típicamente HTTP 451 en runners de CI
    de EE.UU.). Lanza RuntimeError si ambas fuentes fallan.
    """
    try:
        return BinanceProvider().get_ohlcv(f"{simbolo}USDT", INTERVALO, num_velas=VELAS_NECESARIAS)
    except BinanceProviderError as e_binance:
        logger.warning(f"Binance falló para {simbolo} ({e_binance}), probando Yahoo Finance...")
        try:
            ticker = SIMBOLO_A_TICKER_YAHOO[simbolo]
            return YahooProvider().get_daily_history(ticker, period="2y")
        except YahooProviderError as e_yahoo:
            raise RuntimeError(
                f"No se pudo obtener velas de {simbolo} ni por Binance ni por Yahoo Finance "
                f"(Binance: {e_binance} | Yahoo: {e_yahoo})"
            ) from e_yahoo


def calcular_indicadores(simbolo: str) -> dict:
    """Descarga velas 1D (Binance con respaldo en Yahoo Finance) y
    calcula RSI/Estocástico/Williams%R con pandas_ta, más el color de
    la vela de hoy y de ayer para detectar el flip.

    Lanza RuntimeError si no se pudieron obtener datos de ninguna
    fuente (se deja propagar para que quien llame decida si omite esa
    moneda).
    """
    df = obtener_velas(simbolo)

    if len(df) < 2:
        raise RuntimeError(f"Datos insuficientes para {simbolo} ({len(df)} velas, se necesitan al menos 2)")

    apertura, alto, bajo, cierre = df["Open"], df["High"], df["Low"], df["Close"]
    rsi = ta.rsi(cierre, length=RSI_PERIODO)
    stoch = ta.stoch(alto, bajo, cierre, k=STOCH_K, d=STOCH_D, smooth_k=STOCH_SUAVIZADO)
    willr = ta.willr(alto, bajo, cierre, length=WILLR_PERIODO)

    if rsi is None or stoch is None or willr is None:
        raise RuntimeError(f"No se pudieron calcular los indicadores de {simbolo} ({len(df)} velas disponibles)")

    stoch_k = stoch.iloc[:, 0]

    def color_de(idx: int) -> str:
        if cierre.iloc[idx] > apertura.iloc[idx]:
            return "verde"
        if cierre.iloc[idx] < apertura.iloc[idx]:
            return "roja"
        return "doji"

    return {
        "simbolo": simbolo,
        "precio": float(cierre.iloc[-1]),
        "rsi": float(rsi.iloc[-1]),
        "stoch_k": float(stoch_k.iloc[-1]),
        "willr": float(willr.iloc[-1]),
        "color_hoy": color_de(-1),
        "color_ayer": color_de(-2),
    }


def evaluar_senal(indicadores: dict) -> dict | None:
    """Aplica la regla de entrada validada por backtesting (730 días,
    universo de 7 monedas, ver docstring del módulo) - sin criterio
    adicional:

    LARGO solo si: vela de ayer roja Y vela de hoy verde Y RSI hoy < 30
    CORTO solo si: vela de ayer verde Y vela de hoy roja Y Estocástico
                   hoy > 80 Y Williams%R hoy > -20
    """
    precio = indicadores["precio"]
    rsi = indicadores["rsi"]
    stoch_k = indicadores["stoch_k"]
    willr = indicadores["willr"]
    color_hoy = indicadores["color_hoy"]
    color_ayer = indicadores["color_ayer"]

    flip_a_verde = color_ayer == "roja" and color_hoy == "verde"
    flip_a_roja = color_ayer == "verde" and color_hoy == "roja"

    if flip_a_verde and rsi < RSI_SOBREVENTA_GATILLO:
        return {
            "direccion": "LARGO",
            "precio_entrada": precio,
            "stop_loss": precio * (1 - STOP_LOSS_PCT),
            "take_profit": precio * (1 + TAKE_PROFIT_PCT),
            "razon": f"vela pasó de roja a verde + RSI en sobreventa ({rsi:.1f})",
        }

    if flip_a_roja and stoch_k > STOCH_SOBRECOMPRA_GATILLO and willr > WILLR_SOBRECOMPRA_GATILLO:
        return {
            "direccion": "CORTO",
            "precio_entrada": precio,
            "stop_loss": precio * (1 + STOP_LOSS_PCT),
            "take_profit": precio * (1 - TAKE_PROFIT_PCT),
            "razon": f"vela pasó de verde a roja + Estocástico ({stoch_k:.1f}) y Williams%R ({willr:.1f}) en sobrecompra",
        }

    return None


def armar_tabla(resultados: list[dict]) -> str:
    """Tabla de precio/RSI/color de vela en bloque de código
    (monoespaciado), para que Telegram alinee las columnas de verdad -
    el Markdown "legacy" que usa el bot no soporta tablas, solo texto
    plano y bloques ```pre```, que sí respetan el ancho fijo de cada
    columna.
    """
    encabezado = f"{'Moneda':<7}{'Precio':>14}{'RSI':>8}  Vela hoy"
    filas = [encabezado, "-" * len(encabezado)]
    for r in resultados:
        precio_fmt = f"${r['precio']:,.4f}"
        filas.append(f"{r['simbolo']:<7}{precio_fmt:>14}{r['rsi']:>8.2f}  {r['color_hoy'].capitalize()}")
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
