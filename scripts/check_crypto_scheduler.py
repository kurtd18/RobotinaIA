"""
Ejecuta UNA sola corrida del pipeline completo del scheduler crypto
(Fase 10), sin esperar a los horarios programados (06:00/10:00/14:00/
18:00 Colombia) y sin pasar por la idempotencia (para poder probarlo
en cualquier momento del día). Contra APIs públicas reales. Solo
lectura respecto a trading real: no ejecuta ninguna orden, no conecta
ninguna cuenta real, no usa API keys privadas - solo corre scoring,
paper trading (simulado) y notificaciones de Telegram si aplica.

Uso: python -m scripts.check_crypto_scheduler
"""

from app.scheduler.crypto_scheduler import ZONA_COLOMBIA, ejecutar_analisis_programado, hora_colombia_actual


def check_crypto_scheduler():
    ahora = hora_colombia_actual()
    print(f"Timezone detectada para el scheduler: {ZONA_COLOMBIA} (zoneinfo, no depende del servidor)")
    print(f"Hora Colombia actual: {ahora.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("\nEjecutando UNA corrida manual del pipeline completo (BTC/USDT, ETH/USDT)...\n")

    resultado = ejecutar_analisis_programado(ahora)

    for symbol, pipeline in resultado["resultados"].items():
        print(f"\n--- {symbol} ---")
        if pipeline is None:
            print("ERROR: no se pudo completar el análisis (ver log arriba)")
            continue

        r = pipeline["resultado"]
        print(f"Score total: {r['total_score']}/100")
        print(f"Confidence: {r['confidence']}%")
        print(f"Señal: {r['signal']}")
        print(f"Cambio de señal: {r['cambio_senal'] if r['cambio_senal'] else 'sin cambio'}")
        print(f"Métricas sin datos: {len(r['metricas_sin_datos'])}")

        paper = pipeline["paper_resultado"]
        if paper:
            print(f"Paper trading - cerradas: {len(paper.get('posiciones_cerradas', []))}, "
                  f"abierta: {'sí' if paper.get('posicion_abierta') else 'no'}")

        enviados = pipeline["telegram_enviados"]
        print(f"Telegram: {'enviado (' + str(len(enviados)) + ' mensaje(s))' if enviados else 'no enviado'}")

    print(f"\nDuración total: {resultado['duracion_segundos']:.1f} segundos")
    print(f"Errores: {len(resultado['errores'])}")
    for e in resultado["errores"]:
        print(f"  - {e}")


if __name__ == "__main__":
    check_crypto_scheduler()
