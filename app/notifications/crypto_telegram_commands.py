"""
Comando manual /cripto del bot de Telegram (Fase 9).

A propósito corre el motor con persistir=False: una consulta manual bajo
demanda NO debe quedar guardada como si fuera la corrida oficial de cada
4 horas, porque eso rompería la detección de cambio de señal (una
consulta repetida no debe "consumir" el cambio de señal) y no debe
abrir posiciones de paper trading por sí sola (eso solo lo hace la
corrida programada, ver scripts/check_paper_trading.py). Es de solo
lectura: no conecta ninguna cuenta real ni ejecuta ninguna operación.
"""

from app.scheduler.crypto_pipeline import run_crypto_analysis
from app.scoring.crypto_scoring_engine import SIMBOLOS_SOPORTADOS


def _formatear(resultado: dict) -> str:
    return (
        f"{resultado['symbol']}\n"
        f"Score: {resultado['total_score']:.1f}/100 | Confidence: {resultado['confidence']:.1f}%\n"
        f"Señal: {resultado['signal']}"
        + (f" (candidata {resultado['signal_candidata']} descartada por riesgo/beneficio)"
           if resultado['signal'] != resultado['signal_candidata'] else "")
        + f"\n  Fundamental: {resultado['score_fundamental']:.1f}/30"
        + f" | Técnico: {resultado['score_tecnico']:.1f}/30"
        + f" | Derivados: {resultado['score_derivados']:.1f}/20"
        + f" | Sentimiento: {resultado['score_sentimiento']:.1f}/10"
        + f" | Macro: {resultado['score_macro']:.1f}/10"
    )


def cripto_command() -> str:
    bloques = []

    for symbol in SIMBOLOS_SOPORTADOS:
        try:
            pipeline = run_crypto_analysis(
                symbol, persistir=False, paper_trading=False, notificar_telegram=False
            )
            bloques.append(_formatear(pipeline["resultado"]))
        except Exception as e:
            bloques.append(f"{symbol}: error generando el análisis ({e})")

    return "📊 RobotinaIA Crypto\n\n" + "\n\n".join(bloques)
