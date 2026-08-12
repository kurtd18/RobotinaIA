"""
Corrida manual completa: CryptoScoringEngine (Fase 7) + PaperTradingEngine
(Fase 8) + notificaciones de Telegram (Fase 9), contra APIs públicas
reales. Solo notifica si hay cambio de señal o eventos de paper trading
- no manda un mensaje si todo sigue igual.

Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID configurados en .env
para que el envío real funcione (si no están, enviar_mensaje_telegram
ya maneja el fallo sin romper el script, ver app/services/telegram_service.py).

Uso: python -m scripts.check_crypto_notifications
"""

from app.notifications.crypto_telegram import notificar
from app.paper_trading.paper_trading_engine import PaperTradingEngine
from app.scoring.crypto_scoring_engine import SIMBOLOS_SOPORTADOS, CryptoScoringEngine

SIMBOLOS = list(SIMBOLOS_SOPORTADOS)


def check_crypto_notifications():
    scoring_engine = CryptoScoringEngine()
    paper_engine = PaperTradingEngine()

    for symbol in SIMBOLOS:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")

        resultado = scoring_engine.analizar(symbol)
        print(f"Score: {resultado['total_score']}/100 | confidence: {resultado['confidence']}% | señal: {resultado['signal']}")

        paper_resultado = paper_engine.procesar(symbol, resultado)

        enviados = notificar(symbol, resultado, paper_resultado)

        if enviados:
            print(f"Notificaciones enviadas ({len(enviados)}):")
            for m in enviados:
                print(f"---\n{m}")
        else:
            print("Sin eventos que notificar (sin cambio de señal, sin apertura/cierre de posición)")


if __name__ == "__main__":
    check_crypto_notifications()
