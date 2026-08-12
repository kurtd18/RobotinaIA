"""
PaperTradingEngine - Fase 8 de RobotinaIA Crypto.

100% simulado: no conecta ninguna cuenta real, no usa API keys
privadas, no ejecuta ninguna orden real. Solo registra en SQLite qué
habría pasado si se hubiera operado cada señal LONG/SHORT que produce
CryptoScoringEngine (Fase 7), para medir el desempeño del sistema antes
de considerar operar con dinero real.

Reglas (decididas explícitamente, ver conversación):
- Apertura: automática cada vez que el engine produce LONG o SHORT (ya
  pasó el gate de riesgo/beneficio de Fase 7). No se abre una segunda
  posición si ya hay una abierta para el mismo símbolo.
- Cierre: al tocar el stop o el target, revisado en cada corrida
  posterior contra el precio actual.
- Tamaño: capital simulado fijo por posición (CAPITAL_POR_POSICION USDT
  nocional), convertido a cantidad de BTC/ETH según el precio de entrada.
"""

from datetime import datetime, timezone

from loguru import logger

from app.paper_trading import repository
from app.providers.binance_provider import BinanceProvider, BinanceProviderError

CAPITAL_POR_POSICION_USDT = 1000.0


class PaperTradingEngine:
    def __init__(self, provider: BinanceProvider = None, capital_por_posicion: float = CAPITAL_POR_POSICION_USDT):
        self.provider = provider or BinanceProvider()
        self.capital_por_posicion = capital_por_posicion

    def procesar(self, symbol: str, resultado_engine: dict) -> dict:
        """
        Punto de entrada principal: revisa si alguna posición abierta de
        `symbol` tocó stop/target con el precio actual, y si la señal del
        `resultado_engine` (de CryptoScoringEngine.analizar) es LONG o
        SHORT, abre una posición nueva (si no hay ya una abierta).

        Devuelve {"posiciones_cerradas": [...], "posicion_abierta": {...} | None}
        """
        try:
            precio_actual = self._precio_actual(symbol)
        except BinanceProviderError as e:
            logger.error(f"No se pudo obtener precio actual para paper trading de {symbol}: {e}")
            return {"posiciones_cerradas": [], "posicion_abierta": None, "error": str(e)}

        posiciones_cerradas = self.revisar_posiciones_abiertas(symbol, precio_actual)

        posicion_abierta = None
        señal = resultado_engine.get("signal")
        if señal in ("LONG", "SHORT"):
            posicion_abierta = self.abrir_posicion(symbol, señal, resultado_engine)

        return {"posiciones_cerradas": posiciones_cerradas, "posicion_abierta": posicion_abierta}

    def abrir_posicion(self, symbol: str, direction: str, resultado_engine: dict) -> dict | None:
        if repository.obtener_posiciones_abiertas(symbol):
            logger.info(f"Ya hay una posición de paper trading abierta para {symbol}, no se abre otra")
            return None

        riesgo = resultado_engine.get("risk_reward")
        if not riesgo or not riesgo.get("disponible"):
            logger.warning(f"Señal {direction} sin risk_reward disponible, no se abre posición para {symbol}")
            return None

        entry_price = riesgo["entry"]
        stop_price = riesgo["stop"]
        target_price = riesgo["target"]
        quantity = self.capital_por_posicion / entry_price

        posicion = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "size_usdt": self.capital_por_posicion,
            "quantity": quantity,
            "opened_at": datetime.now(timezone.utc),
            "scoring_id": resultado_engine.get("id"),
        }

        posicion["id"] = repository.guardar_posicion_abierta(posicion)
        logger.info(
            f"Paper trading: abierta posición {direction} {symbol} @ {entry_price:.2f} "
            f"(stop={stop_price:.2f}, target={target_price:.2f}, size={self.capital_por_posicion} USDT)"
        )
        return posicion

    def revisar_posiciones_abiertas(self, symbol: str, precio_actual: float) -> list[dict]:
        cerradas = []

        for pos in repository.obtener_posiciones_abiertas(symbol):
            cierre = self._evaluar_cierre(pos, precio_actual)
            if cierre is None:
                continue

            close_price, reason = cierre
            pnl_usdt, pnl_pct = self._calcular_pnl(pos, close_price)
            closed_at = datetime.now(timezone.utc)

            repository.cerrar_posicion(pos["id"], close_price, reason, pnl_usdt, pnl_pct, closed_at)

            pos.update({
                "close_price": close_price, "close_reason": reason,
                "pnl_usdt": pnl_usdt, "pnl_pct": pnl_pct, "closed_at": closed_at,
            })
            cerradas.append(pos)

            logger.info(
                f"Paper trading: cerrada posición {pos['direction']} {symbol} por {reason} "
                f"@ {close_price:.2f} (PnL: {pnl_usdt:+.2f} USDT / {pnl_pct:+.2f}%)"
            )

        return cerradas

    def _evaluar_cierre(self, pos: dict, precio_actual: float):
        if pos["direction"] == "LONG":
            if precio_actual <= pos["stop_price"]:
                return pos["stop_price"], "STOP"
            if precio_actual >= pos["target_price"]:
                return pos["target_price"], "TARGET"
        else:  # SHORT
            if precio_actual >= pos["stop_price"]:
                return pos["stop_price"], "STOP"
            if precio_actual <= pos["target_price"]:
                return pos["target_price"], "TARGET"
        return None

    def _calcular_pnl(self, pos: dict, close_price: float) -> tuple[float, float]:
        if pos["direction"] == "LONG":
            pnl_usdt = (close_price - pos["entry_price"]) * pos["quantity"]
        else:  # SHORT
            pnl_usdt = (pos["entry_price"] - close_price) * pos["quantity"]

        pnl_pct = (pnl_usdt / pos["size_usdt"]) * 100
        return pnl_usdt, pnl_pct

    def _precio_actual(self, symbol: str) -> float:
        data = self.provider.get_ohlcv(symbol, "1h", num_velas=1)
        return float(data["Close"].iloc[-1])
