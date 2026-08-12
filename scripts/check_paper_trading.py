"""
Corrida manual de CryptoScoringEngine (Fase 7) + PaperTradingEngine
(Fase 8) contra APIs públicas reales. 100% simulado: no conecta ninguna
cuenta real, no usa API keys privadas, no ejecuta ninguna orden real.
Persiste en robotinaia.db (tablas crypto_scores y paper_positions).

Uso: python -m scripts.check_paper_trading
"""

from app.paper_trading import repository as paper_repository
from app.paper_trading.paper_trading_engine import PaperTradingEngine
from app.scoring.crypto_scoring_engine import SIMBOLOS_SOPORTADOS, CryptoScoringEngine

SIMBOLOS = list(SIMBOLOS_SOPORTADOS)


def check_paper_trading():
    scoring_engine = CryptoScoringEngine()
    paper_engine = PaperTradingEngine()

    for symbol in SIMBOLOS:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")

        resultado = scoring_engine.analizar(symbol)
        print(f"Score total: {resultado['total_score']}/100 | confidence: {resultado['confidence']}% | señal: {resultado['signal']}")

        paper_resultado = paper_engine.procesar(symbol, resultado)

        if paper_resultado.get("error"):
            print(f"Paper trading: error obteniendo precio actual - {paper_resultado['error']}")
            continue

        for cerrada in paper_resultado["posiciones_cerradas"]:
            print(
                f"CERRADA: {cerrada['direction']} {symbol} entry={cerrada['entry_price']:.2f} "
                f"close={cerrada['close_price']:.2f} razón={cerrada['close_reason']} "
                f"PnL={cerrada['pnl_usdt']:+.2f} USDT ({cerrada['pnl_pct']:+.2f}%)"
            )

        if paper_resultado["posicion_abierta"]:
            p = paper_resultado["posicion_abierta"]
            print(
                f"ABIERTA: {p['direction']} {symbol} entry={p['entry_price']:.2f} "
                f"stop={p['stop_price']:.2f} target={p['target_price']:.2f} "
                f"tamaño={p['size_usdt']} USDT ({p['quantity']:.6f} unidades)"
            )
        elif not paper_resultado["posiciones_cerradas"]:
            print("Sin cambios en paper trading (no se abrió ni se cerró ninguna posición)")

    print(f"\n{'=' * 70}\nHISTORIAL COMPLETO DE PAPER TRADING\n{'=' * 70}")
    historial = paper_repository.obtener_historial()
    if not historial:
        print("(sin posiciones registradas todavía)")
    for pos in historial:
        estado = pos["status"]
        linea = f"#{pos['id']} {pos['symbol']} {pos['direction']} {estado} entry={pos['entry_price']:.2f}"
        if estado == "CLOSED":
            linea += f" close={pos['close_price']:.2f} razón={pos['close_reason']} PnL={pos['pnl_usdt']:+.2f} USDT"
        print(linea)

    cerradas = [p for p in historial if p["status"] == "CLOSED"]
    if cerradas:
        pnl_total = sum(p["pnl_usdt"] for p in cerradas)
        ganadoras = sum(1 for p in cerradas if p["pnl_usdt"] > 0)
        print(f"\nResumen: {len(cerradas)} cerradas, {ganadoras} ganadoras, PnL total={pnl_total:+.2f} USDT")


if __name__ == "__main__":
    check_paper_trading()
