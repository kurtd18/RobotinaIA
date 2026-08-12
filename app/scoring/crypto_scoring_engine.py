"""
CryptoScoringEngine - Fase 7 de RobotinaIA Crypto.

Combina fundamental (30) + técnico (30) + derivados (20) + sentimiento
(10) + macro (10) = 100 puntos, calcula confidence por separado, aplica
las reglas de señal (LONG/SHORT/NO_OPERAR) y el gate de riesgo/beneficio
mínimo, detecta cambios de señal respecto al último resultado guardado,
y persiste todo en SQLite.

NO conecta cuentas reales, NO usa API keys privadas, NO ejecuta
operaciones. Es exclusivamente el motor de análisis.
"""

from datetime import datetime, timezone

from loguru import logger

from app.scoring import repository
from app.scoring.confidence import calcular_confidence
from app.scoring.derivatives_score import calcular_score_derivados
from app.scoring.fundamental_score import calcular_score_fundamental
from app.scoring.macro_score import calcular_score_macro
from app.scoring.risk_validation import calcular_risk_reward
from app.scoring.sentiment_score import calcular_score_sentimiento
from app.scoring.technical_score import calcular_score_tecnico

PUNTOS_TOTALES_POR_CATEGORIA = {
    "fundamental": 30, "tecnico": 30, "derivados": 20, "sentimiento": 10, "macro": 10,
}

UMBRAL_LONG_SCORE = 75
UMBRAL_SHORT_SCORE = 35
UMBRAL_CONFIDENCE = 70
RATIO_RIESGO_BENEFICIO_MINIMO = 1.5

SIMBOLOS_SOPORTADOS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
)
# TONUSDT se retiró: Binance lo tenía en estado "BREAK" (trading
# pausado), sin velas nuevas - quedaba siempre sin datos. Reemplazado
# por DOTUSDT (Polkadot), confirmado "TRADING" en spot y futuros.


class CryptoScoringEngine:
    def __init__(self, binance_provider=None, blockchain_provider=None, defillama_provider=None,
                 coingecko_provider=None, feargreed_provider=None, macro_provider=None):
        self.binance_provider = binance_provider
        self.blockchain_provider = blockchain_provider
        self.defillama_provider = defillama_provider
        self.coingecko_provider = coingecko_provider
        self.feargreed_provider = feargreed_provider
        self.macro_provider = macro_provider

    def analizar(self, symbol: str, persistir: bool = True) -> dict:
        if symbol not in SIMBOLOS_SOPORTADOS:
            raise ValueError(f"Símbolo '{symbol}' no soportado. Usa uno de: {SIMBOLOS_SOPORTADOS}")

        logger.info(f"=== CryptoScoringEngine: analizando {symbol} ===")

        categorias = {
            "fundamental": calcular_score_fundamental(
                symbol, self.blockchain_provider, self.defillama_provider, self.coingecko_provider
            ),
            "tecnico": calcular_score_tecnico(symbol, self.binance_provider),
            "derivados": calcular_score_derivados(symbol, self.binance_provider),
            "sentimiento": calcular_score_sentimiento(self.feargreed_provider),
            "macro": calcular_score_macro(self.macro_provider),
        }

        scores_por_categoria = {}
        for nombre, cat in categorias.items():
            maximo = PUNTOS_TOTALES_POR_CATEGORIA[nombre]
            if cat.get("disponible") and cat.get("puntos") is not None:
                scores_por_categoria[nombre] = cat["puntos"]
            else:
                # sin datos en toda la categoría: no se penaliza con 0 ni
                # se asume favorable - se usa el punto medio (neutral)
                scores_por_categoria[nombre] = maximo * 0.5
                logger.warning(f"Categoría '{nombre}' sin datos para {symbol}, se usa valor neutral")

        total_score = round(sum(scores_por_categoria.values()), 2)

        confidence_resultado = calcular_confidence(categorias, PUNTOS_TOTALES_POR_CATEGORIA)
        confidence = confidence_resultado["confidence"]

        señal_candidata, motivo_candidata = self._determinar_senal_candidata(total_score, confidence)

        riesgo = None
        señal_final = señal_candidata
        motivo_riesgo = None

        if señal_candidata in ("LONG", "SHORT"):
            riesgo = calcular_risk_reward(symbol, señal_candidata, self.binance_provider)
            if not riesgo["cumple_minimo"]:
                señal_final = "NO_OPERAR"
                ratio_texto = "no disponible" if not riesgo["disponible"] else f"{riesgo['ratio']:.2f}"
                motivo_riesgo = (
                    f"Señal candidata {señal_candidata} descartada: relación riesgo/beneficio "
                    f"{ratio_texto} no alcanza el mínimo {RATIO_RIESGO_BENEFICIO_MINIMO}"
                )
            else:
                motivo_riesgo = f"Relación riesgo/beneficio {riesgo['ratio']:.2f} cumple el mínimo {RATIO_RIESGO_BENEFICIO_MINIMO}"

        anterior = repository.obtener_ultima_senal(symbol)
        cambio_senal = None
        if anterior is not None and anterior["signal"] != señal_final:
            cambio_senal = {"de": anterior["signal"], "a": señal_final}
            logger.info(f"Cambio de señal detectado para {symbol}: {anterior['signal']} -> {señal_final}")

        razones = [motivo_candidata]
        if motivo_riesgo:
            razones.append(motivo_riesgo)
        if cambio_senal:
            razones.append(f"Cambio de señal respecto al último análisis: {cambio_senal['de']} -> {cambio_senal['a']}")

        metricas_sin_datos = self._listar_metricas_sin_datos(categorias)

        resultado = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "score_fundamental": scores_por_categoria["fundamental"],
            "score_tecnico": scores_por_categoria["tecnico"],
            "score_derivados": scores_por_categoria["derivados"],
            "score_sentimiento": scores_por_categoria["sentimiento"],
            "score_macro": scores_por_categoria["macro"],
            "total_score": total_score,
            "confidence": confidence,
            "confidence_factores": confidence_resultado["factores"],
            "signal": señal_final,
            "signal_candidata": señal_candidata,
            "cambio_senal": cambio_senal,
            "risk_reward": riesgo,
            "razones": razones,
            "metricas_sin_datos": metricas_sin_datos,
            "detalle_categorias": categorias,
        }

        if persistir:
            id_guardado = repository.guardar_resultado(resultado)
            resultado["id"] = id_guardado
            logger.info(f"Resultado de {symbol} persistido con id={id_guardado}")

        logger.info(
            f"OK: {symbol} total_score={total_score}/100 confidence={confidence}% signal={señal_final}"
        )
        return resultado

    def _determinar_senal_candidata(self, total_score: float, confidence: float) -> tuple[str, str]:
        if total_score >= UMBRAL_LONG_SCORE and confidence >= UMBRAL_CONFIDENCE:
            return "LONG", (
                f"score {total_score} >= {UMBRAL_LONG_SCORE} y confidence {confidence}% "
                f">= {UMBRAL_CONFIDENCE}% -> candidata LONG"
            )
        if total_score <= UMBRAL_SHORT_SCORE and confidence >= UMBRAL_CONFIDENCE:
            return "SHORT", (
                f"score {total_score} <= {UMBRAL_SHORT_SCORE} y confidence {confidence}% "
                f">= {UMBRAL_CONFIDENCE}% -> candidata SHORT"
            )
        return "NO_OPERAR", (
            f"score {total_score} y confidence {confidence}% no cumplen los umbrales de "
            f"LONG (score>={UMBRAL_LONG_SCORE}, confidence>={UMBRAL_CONFIDENCE}) ni de "
            f"SHORT (score<={UMBRAL_SHORT_SCORE}, confidence>={UMBRAL_CONFIDENCE})"
        )

    def _listar_metricas_sin_datos(self, categorias: dict) -> list[str]:
        sin_datos = []
        for nombre, cat in categorias.items():
            if nombre == "tecnico" and "por_timeframe" in cat:
                for tf_nombre, tf in cat["por_timeframe"].items():
                    for m in tf.get("metricas", []):
                        if m.get("senal") == "sin_datos":
                            sin_datos.append(f"tecnico.{tf_nombre}.{m['metrica']}")
            else:
                for m in cat.get("metricas", []):
                    if m.get("senal") == "sin_datos":
                        sin_datos.append(f"{nombre}.{m['metrica']}")
        return sin_datos
