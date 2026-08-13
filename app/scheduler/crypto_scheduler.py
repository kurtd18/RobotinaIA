"""
Scheduler automático del análisis crypto (Fase 10).

Corre cada hora en punto (minuto :00), solo entre VENTANA_HORA_INICIO y
VENTANA_HORA_FIN (6:00 AM - 10:00 PM) hora de Colombia (America/Bogota),
sin importar la zona horaria del servidor donde corra el proceso -
siempre convierte explícitamente con zoneinfo, nunca asume que "la hora
del sistema" ya es Bogotá ni hace aritmética manual de offsets UTC.

Este módulo NO contiene lógica de decisión de trading: solo decide
CUÁNDO llamar a run_crypto_analysis() (Fase 10, app/scheduler/
crypto_pipeline.py), que a su vez reutiliza los motores ya construidos
en fases anteriores.

Manejo de errores (todos no-fatales para el scheduler):
- Si falla la obtención de datos de una fuente, cada categoría de
  CryptoScoringEngine (Fase 7) ya la marca como sin_datos y sigue.
- Si BTC falla catastróficamente (excepción no controlada), se registra
  el error y de todas formas se intenta analizar ETH, y viceversa.
- Si Telegram falla, ya se maneja sin excepción dentro de
  enviar_mensaje_telegram (Fase 9) y dentro de run_crypto_analysis.
- El loop del scheduler nunca se cae por un error de una corrida.
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.notifications.crypto_telegram import notificar, notificar_resumen_global
from app.scheduler import repository
from app.scheduler.crypto_pipeline import run_crypto_analysis
from app.scoring.crypto_scoring_engine import SIMBOLOS_SOPORTADOS

ZONA_COLOMBIA = ZoneInfo("America/Bogota")

# Antes eran 4 horarios fijos (06/10/14/18); ahora corre cada hora en
# punto, así que HORARIOS_PROGRAMADOS ya no es una lista fija - se
# calcula dinámicamente en debe_ejecutar_ahora() según el minuto actual.
INTERVALO_VERIFICACION_SEGUNDOS = 30

# Ventana horaria: no se ejecuta de madrugada (pedido explícito) - solo
# entre las 6:00 AM y las 10:00 PM hora de Colombia, ambos límites
# inclusive (corre a las 06:00 y a las 22:00, no a las 23:00 ni antes
# de las 06:00).
VENTANA_HORA_INICIO = 6
VENTANA_HORA_FIN = 22


def hora_colombia_actual() -> datetime:
    """Hora actual, siempre convertida explícitamente a America/Bogota
    (nunca se asume que datetime.now() del servidor ya está en esa zona)."""
    return datetime.now(ZONA_COLOMBIA)


def debe_ejecutar_ahora(ahora: datetime) -> str | None:
    """
    Devuelve la ventana de esta hora (ej. "06:00") si `ahora` cae en el
    minuto :00 en hora de Colombia Y dentro de la ventana horaria
    (VENTANA_HORA_INICIO a VENTANA_HORA_FIN), o None si no corresponde
    ejecutar en este instante (fuera de ventana o no es el minuto :00).
    `ahora` puede venir en cualquier zona horaria (incluida naive-UTC de
    otros sistemas) - siempre se convierte explícitamente a
    America/Bogota antes de comparar.
    """
    ahora_bogota = ahora.astimezone(ZONA_COLOMBIA) if ahora.tzinfo else ahora.replace(tzinfo=ZONA_COLOMBIA)

    if ahora_bogota.minute != 0:
        return None
    if not (VENTANA_HORA_INICIO <= ahora_bogota.hour <= VENTANA_HORA_FIN):
        return None

    return ahora_bogota.strftime("%H:00")


def ejecutar_analisis_programado(ahora: datetime = None) -> dict:
    """
    Corre el pipeline completo (run_crypto_analysis) para todos los
    símbolos soportados. Un símbolo que falle no impide analizar los
    demás. El envío a Telegram se hace en dos tandas, en orden: primero
    UN mensaje resumen global (todos los activos, si conviene invertir
    o no), y después un mensaje detallado por cada moneda (más los
    eventos de paper trading que hayan ocurrido). Registra el resumen
    [CRYPTO SCHEDULER] pedido.
    """
    ahora = ahora or hora_colombia_actual()
    inicio = time.monotonic()

    pipelines = {}
    errores = []

    for symbol in SIMBOLOS_SOPORTADOS:
        try:
            pipelines[symbol] = run_crypto_analysis(symbol, notificar_telegram=False)
        except Exception as e:
            logger.exception(f"Fallo no controlado analizando {symbol}, se continúa con el resto")
            errores.append(f"{symbol}: {e}")
            pipelines[symbol] = None

    total_enviados = _notificar_resultados(pipelines, ahora)

    duracion_segundos = time.monotonic() - inicio

    _log_resumen(ahora, pipelines, errores, duracion_segundos, total_enviados)

    return {
        "timestamp_colombia": ahora,
        "resultados": pipelines,
        "errores": errores,
        "duracion_segundos": duracion_segundos,
    }


def _notificar_resultados(pipelines: dict, ahora: datetime) -> int:
    """Manda primero el resumen global y después el detalle por moneda
    (+ eventos de paper trading). Nunca lanza excepción - un fallo de
    Telegram se registra y no detiene el resto de notificaciones."""
    total_enviados = 0

    try:
        resultados_por_symbol = {
            symbol: (p["resultado"] if p else None) for symbol, p in pipelines.items()
        }
        notificar_resumen_global(resultados_por_symbol, ahora.astimezone(ZONA_COLOMBIA))
        total_enviados += 1
    except Exception as e:
        logger.error(f"No se pudo enviar el resumen global de Telegram: {e}")

    for symbol, pipeline in pipelines.items():
        if pipeline is None:
            continue
        try:
            enviados = notificar(symbol, pipeline["resultado"], pipeline["paper_resultado"])
            pipeline["telegram_enviados"] = enviados
            total_enviados += len(enviados)
        except Exception as e:
            logger.error(f"No se pudo enviar la notificación detallada de Telegram para {symbol}: {e}")

    return total_enviados


def ejecutar_ciclo_programado(hora_programada: str, ahora: datetime = None) -> dict | None:
    """
    Reserva la ventana (idempotencia) y, si nadie la había ejecutado ya,
    corre el análisis. Si la ventana ya estaba registrada (reinicio del
    proceso, disparo duplicado), se salta sin volver a analizar nada.
    """
    ahora = ahora or hora_colombia_actual()
    fecha = ahora.astimezone(ZONA_COLOMBIA).date().isoformat()

    if not repository.intentar_registrar_ejecucion(fecha, hora_programada):
        logger.info(
            f"[CRYPTO SCHEDULER] Ventana {fecha} {hora_programada} Colombia ya fue ejecutada, "
            f"se salta (idempotencia)"
        )
        return None

    logger.info(f"[CRYPTO SCHEDULER] Ejecutando ventana {fecha} {hora_programada} Colombia")
    return ejecutar_analisis_programado(ahora)


def _resumen_symbol(resultado_pipeline: dict | None, symbol: str) -> str:
    if resultado_pipeline is None:
        return f"{symbol}: ERROR (ver log)"

    r = resultado_pipeline["resultado"]
    return f"{symbol}: {r['signal']} {r['total_score']:.1f} / confidence {r['confidence']:.1f}"


def _log_resumen(ahora: datetime, resultados: dict, errores: list, duracion_segundos: float,
                  total_enviados: int = 0):
    ahora_bogota = ahora.astimezone(ZONA_COLOMBIA)

    telegram_texto = f"{total_enviados} mensaje(s) enviados" if total_enviados else "no enviado"

    total_metricas_sin_datos = sum(
        len(r["resultado"]["metricas_sin_datos"]) for r in resultados.values() if r is not None
    )

    lineas_activos = "\n".join(
        _resumen_symbol(resultados.get(symbol), symbol) for symbol in SIMBOLOS_SOPORTADOS
    )

    mensaje = (
        f"[CRYPTO SCHEDULER]\n"
        f"{ahora_bogota.strftime('%H:%M')} Colombia\n"
        f"{lineas_activos}\n"
        f"Telegram: {telegram_texto}\n"
        f"Duration: {duracion_segundos:.1f} seconds\n"
        f"Errores: {len(errores)}{(' -> ' + '; '.join(errores)) if errores else ''}\n"
        f"Métricas sin datos: {total_metricas_sin_datos}"
    )
    logger.info(mensaje)


def loop_scheduler(intervalo_verificacion_segundos: int = INTERVALO_VERIFICACION_SEGUNDOS):
    """
    Loop infinito: revisa cada `intervalo_verificacion_segundos` si el
    minuto actual en hora de Colombia es :00, y si es así, ejecuta el
    ciclo (con idempotencia) - o sea, corre cada hora en punto. No usa
    la librería `schedule` del proyecto porque esa no permite fijar
    explícitamente la timezone del disparo - acá se compara siempre
    contra America/Bogota calculada con zoneinfo, sin importar dónde
    corra el proceso.
    """
    logger.info(
        f"[CRYPTO SCHEDULER] Iniciado. Corre cada hora en punto entre las "
        f"{VENTANA_HORA_INICIO:02d}:00 y las {VENTANA_HORA_FIN:02d}:00, America/Bogota"
    )

    while True:
        ahora = hora_colombia_actual()
        horario = debe_ejecutar_ahora(ahora)

        if horario:
            try:
                ejecutar_ciclo_programado(horario, ahora)
            except Exception:
                logger.exception("[CRYPTO SCHEDULER] Fallo no controlado en el ciclo programado, se continúa")

        time.sleep(intervalo_verificacion_segundos)
