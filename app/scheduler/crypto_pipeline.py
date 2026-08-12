"""
Función central del pipeline de análisis cripto (Fase 10).

run_crypto_analysis() NO contiene lógica de decisión propia - solo
orquesta, en orden, los servicios ya construidos en fases anteriores:
CryptoScoringEngine (Fase 7, que a su vez ya cubre market data,
técnico, fundamental/on-chain, derivados, sentimiento, macro, scores,
confidence y señal), PaperTradingEngine (Fase 8) y las notificaciones
de Telegram (Fase 9). Es la única función que arma ese flujo completo -
tanto el scheduler como el comando /cripto y los scripts manuales la
reutilizan, para no duplicar la orquestación en varios lugares.
"""

from loguru import logger

from app.notifications.crypto_telegram import notificar
from app.paper_trading.paper_trading_engine import PaperTradingEngine
from app.scoring.crypto_scoring_engine import CryptoScoringEngine


def run_crypto_analysis(symbol: str, persistir: bool = True, paper_trading: bool = True,
                         notificar_telegram: bool = True, scoring_engine: CryptoScoringEngine = None,
                         paper_engine: PaperTradingEngine = None) -> dict:
    """
    Ejecuta el pipeline completo para un símbolo (BTCUSDT o ETHUSDT):
    1-9. CryptoScoringEngine.analizar() (market data, técnico,
         fundamental/on-chain, derivados, sentimiento, macro, scores,
         confidence, señal - todo ya implementado en Fase 7).
    10.  Persistencia del snapshot (parámetro `persistir`, delegado al engine).
    11.  Paper trading (parámetro `paper_trading`, Fase 8).
    12.  Detección de cambio de señal (ya la hace CryptoScoringEngine.analizar()).
    13.  Notificaciones de Telegram (parámetro `notificar_telegram`, Fase 9).

    persistir=False / paper_trading=False / notificar_telegram=False
    permiten consultas de solo lectura (ej. el comando /cripto) sin
    afectar el historial de señales ni abrir posiciones de papel.

    Nunca lanza una excepción por fallos de paper trading o Telegram -
    esos se degradan de forma segura y quedan registrados en el log y
    en el resultado. Un fallo real del motor de scoring (símbolo
    inválido, etc.) sí se propaga - quien llama a esta función por cada
    símbolo por separado (el scheduler) decide cómo aislar esos errores.
    """
    scoring_engine = scoring_engine or CryptoScoringEngine()

    resultado = scoring_engine.analizar(symbol, persistir=persistir)

    paper_resultado = None
    if paper_trading:
        paper_engine = paper_engine or PaperTradingEngine()
        try:
            paper_resultado = paper_engine.procesar(symbol, resultado)
        except Exception as e:
            logger.error(f"Paper trading falló para {symbol}, se continúa sin él: {e}")
            paper_resultado = {"posiciones_cerradas": [], "posicion_abierta": None, "error": str(e)}

    telegram_enviados = []
    if notificar_telegram:
        try:
            telegram_enviados = notificar(symbol, resultado, paper_resultado)
        except Exception as e:
            logger.error(f"Notificación de Telegram falló para {symbol}, se continúa: {e}")

    return {
        "symbol": symbol,
        "resultado": resultado,
        "paper_resultado": paper_resultado,
        "telegram_enviados": telegram_enviados,
    }
