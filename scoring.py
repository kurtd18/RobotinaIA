"""
Motor de scoring técnico de RobotinaIA.
Analiza los activos configurados, calcula un score técnico y
genera/envía señales cuando el score supera el umbral.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd

from loguru import logger

from app.core.settings import Settings
from app.database import guardar_senal, existe_senal_pendiente
from app.indicators.technical_indicators import agregar_todos_los_indicadores
from app.services.alert_engine import AlertEngine
from app.services.telegram_service import enviar_mensaje_telegram

ACTIVOS = Settings.todos_los_activos()

UMBRAL_SENAL = Settings.UMBRAL_SENAL

STOP_INICIAL_PCT = 0.01     # -1% desde la entrada
OBJETIVO_INICIAL_PCT = 0.03  # +3% desde la entrada

# ATR relativo al precio (%), en vez de un número fijo. Un ATR absoluto de
# "30" no tiene sentido comparado entre activos de escalas de precio muy
# distintas (ej. ECOPETROL.CL ~2,500 vs CIBEST.CL ~83,500 vs AAPL ~337) -
# calibrado con datos reales el 28/07/2026, sujeto a ajuste con más evidencia.
ATR_PCT_THRESHOLD = 0.3

alert_engine = AlertEngine()


def _mayor_que(a, b):
    """Compara a > b de forma segura: si falta algún dato (None/NaN,
    activo de baja liquidez con pocas velas), la condición se toma como
    no cumplida en vez de tronar."""

    if pd.isna(a) or pd.isna(b):
        return False

    return a > b


def _atr_relativo(atr, close):
    """Calcula el ATR como porcentaje del precio. None si no se puede calcular."""

    if pd.isna(atr) or pd.isna(close) or close == 0:
        return None

    return (atr / close) * 100


def calcular_score(data):
    """Calcula el score técnico (0-100) y el precio de cierre más reciente."""

    score = 0

    data = agregar_todos_los_indicadores(data)
    ultimo = data.iloc[-1]

    if _mayor_que(ultimo["RSI"], 50):
        score += 10

    if _mayor_que(ultimo["EMA9"], ultimo["EMA21"]):
        score += 10

    if _mayor_que(ultimo["Close"], ultimo["VWAP"]):
        score += 20

    if _mayor_que(ultimo["MACD_12_26_9"], ultimo["MACDs_12_26_9"]):
        score += 10

    if _mayor_que(ultimo["Volume"], ultimo["VOL_AVG"]):
        score += 15

    atr_pct = _atr_relativo(ultimo["ATR"], ultimo["Close"])
    if _mayor_que(atr_pct, ATR_PCT_THRESHOLD):
        score += 5

    if _mayor_que(ultimo["MOM14"], 0):
        score += 15

    if _mayor_que(ultimo["Close"], ultimo["BBU_20_2.0_2.0"]):
        score += 10

    # Peso temporal
    score += 5

    return score, float(ultimo["Close"])


def enviar_telegram(signal_id, activo, score, precio, ahora):
    """Envía una alerta de oportunidad detectada por Telegram."""

    stop_sugerido = precio * (1 - STOP_INICIAL_PCT)
    objetivo_sugerido = precio * (1 + OBJETIVO_INICIAL_PCT)
    recomendacion = alert_engine.get_recommendation(score)

    mensaje = f"""
🤖 ROBOTINAIA

✅ OPORTUNIDAD DETECTADA

📈 Activo: {activo}

⭐ Score: {score}/100 ({recomendacion})

💲 Precio: {precio:.2f}

🕒 Hora: {ahora}

🎯 Stop sugerido (-1%): {stop_sugerido:.2f}
🎯 Objetivo sugerido (+3%): {objetivo_sugerido:.2f}

Para comprar, responde con la cantidad:
/buy {signal_id} CANTIDAD
"""

    codigo = enviar_mensaje_telegram(mensaje)

    logger.info(f"{activo} -> TELEGRAM ({codigo})")


def analizar_activos(activos, ahora):
    """Descarga datos y calcula el score de cada activo."""

    resultados = []

    for activo in activos:
        try:
            data = yf.Ticker(activo).history(period="5d", interval="5m")

            if data.empty:
                logger.warning(f"{activo}: SIN DATOS")
                continue

            score, precio = calcular_score(data)
            resultados.append({"activo": activo, "score": score, "precio": precio})
            logger.info(f"{activo:15} -> SCORE: {score}")

        except Exception:
            logger.exception(f"{activo}: error calculando score")

    return resultados


def procesar_senales(resultados, ahora):
    """Guarda y notifica las señales que superan el umbral configurado."""

    for r in resultados:
        if r["score"] < UMBRAL_SENAL:
            continue

        try:
            if existe_senal_pendiente(r["activo"]):
                logger.info(f"{r['activo']} -> YA EXISTE UNA SEÑAL PENDIENTE")
                continue

            signal_id = guardar_senal(str(ahora), r["activo"], r["score"], r["precio"])
            enviar_telegram(signal_id, r["activo"], r["score"], r["precio"], ahora)

        except Exception:
            logger.exception(f"{r['activo']}: error procesando señal")


def ejecutar_scoring():
    """Punto de entrada del módulo: corre el ciclo completo de scoring."""

    ahora = datetime.now(ZoneInfo("America/Bogota"))

    logger.info("=" * 80)
    logger.info(f"ROBOTINAIA V6.0 - Hora Colombia: {ahora}")
    logger.info("=" * 80)

    resultados = analizar_activos(ACTIVOS, ahora)
    resultados.sort(key=lambda x: x["score"], reverse=True)

    logger.info("TOP OPORTUNIDADES")
    for r in resultados:
        logger.info(f"{r['activo']:15} {r['score']}")

    logger.info(f"SEÑALES >= {UMBRAL_SENAL}")
    procesar_senales(resultados, ahora)

    logger.info("PROCESO FINALIZADO")


if __name__ == "__main__":
    ejecutar_scoring()