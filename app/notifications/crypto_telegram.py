"""
Notificaciones de Telegram para RobotinaIA Crypto (Fase 9).

Reutiliza app/services/telegram_service.py (ya usado por la estrategia
de acciones), con un parámetro opcional y aditivo (parse_mode) para
poder mandar el resumen con formato HTML (negritas, tabla monoespaciada)
en vez de texto plano.

Regla de disparo (ajustada a pedido explícito):
- SIEMPRE se manda UN mensaje resumen global con los 10 activos (tabla
  compacta: símbolo, señal, score, confidence) - sirve para confirmar
  que el scheduler sigue vivo y trackear la variación en el tiempo.
- El mensaje DETALLADO (desglose por categoría) solo se manda para los
  activos cuya señal sea LONG o SHORT (los que sí hay que operar) - no
  se satura el chat con el detalle de los que quedan en NO_OPERAR.
- Los eventos de paper trading (apertura/cierre) se notifican aparte,
  con el detalle de entry/stop/target/PnL.
"""

from datetime import datetime, timezone

from loguru import logger

from app.services.telegram_service import enviar_mensaje_telegram

_EMOJI_SENAL = {"LONG": "🟢", "SHORT": "🔴", "NO_OPERAR": "⚪"}

ANCHO_SYMBOL = 8
ANCHO_SENAL = 12


def activo_es_operable(resultado: dict | None) -> bool:
    return resultado is not None and resultado["signal"] in ("LONG", "SHORT")


def _fila_tabla(symbol: str, resultado: dict | None) -> str:
    nombre = symbol.replace("USDT", "")

    if resultado is None:
        return f"{nombre.ljust(ANCHO_SYMBOL)}{'ERROR'.ljust(ANCHO_SENAL)}"

    emoji = _EMOJI_SENAL.get(resultado["signal"], "⚪")
    senal = f"{emoji} {resultado['signal']}"
    return (
        f"{nombre.ljust(ANCHO_SYMBOL)}{senal.ljust(ANCHO_SENAL)}"
        f"{resultado['total_score']:>5.1f}  {resultado['confidence']:>5.1f}%"
    )


def _formatear_resumen_global(resultados_por_symbol: dict, ahora: datetime = None) -> str:
    """
    Un solo mensaje con formato HTML: encabezado, tabla alineada
    (símbolo/señal/score/confidence) de todos los activos, y un pie con
    cuáles (si alguno) hay que operar. `resultados_por_symbol` es
    {symbol: resultado_engine | None (si falló)}.
    """
    ahora = ahora or datetime.now(timezone.utc)
    encabezado_tabla = f"{'Activo'.ljust(ANCHO_SYMBOL)}{'Señal'.ljust(ANCHO_SENAL)}Score  Conf."
    separador = "─" * len(encabezado_tabla)

    filas = [_fila_tabla(symbol, resultado) for symbol, resultado in resultados_por_symbol.items()]

    operables = [
        symbol for symbol, r in resultados_por_symbol.items() if activo_es_operable(r)
    ]
    if operables:
        detalle_operables = ", ".join(
            f"{s.replace('USDT', '')} ({resultados_por_symbol[s]['signal']})" for s in operables
        )
        pie = f"⚡ <b>A operar:</b> {detalle_operables}"
    else:
        pie = "😴 Ningún activo cumple los criterios para operar en este momento."

    return (
        f"📊 <b>RobotinaIA Crypto</b> — Resumen\n"
        f"🕒 {ahora.strftime('%Y-%m-%d %H:%M %z')}\n\n"
        f"<pre>{encabezado_tabla}\n{separador}\n" + "\n".join(filas) + "</pre>\n\n"
        f"{pie}"
    )


def notificar_resumen_global(resultados_por_symbol: dict, ahora: datetime = None) -> str:
    """Envía el mensaje resumen global (formato HTML) y devuelve el texto enviado."""
    mensaje = _formatear_resumen_global(resultados_por_symbol, ahora)
    enviar_mensaje_telegram(mensaje, parse_mode="HTML")
    logger.info(f"Notificación de resumen global enviada ({len(resultados_por_symbol)} activos)")
    return mensaje


def _formatear_resumen(symbol: str, resultado: dict) -> str:
    cambio = resultado.get("cambio_senal")
    linea_cambio = (
        f"🔁 Cambio de señal: {cambio['de']} -> {cambio['a']}" if cambio else "Sin cambio de señal"
    )

    return (
        f"📊 RobotinaIA Crypto - {symbol}\n\n"
        f"Señal: {resultado['signal']}\n"
        f"{linea_cambio}\n"
        f"Score total: {resultado['total_score']:.1f}/100 | Confidence: {resultado['confidence']:.1f}%\n\n"
        f"Fundamental: {resultado['score_fundamental']:.1f}/30\n"
        f"Técnico: {resultado['score_tecnico']:.1f}/30\n"
        f"Derivados: {resultado['score_derivados']:.1f}/20\n"
        f"Sentimiento: {resultado['score_sentimiento']:.1f}/10\n"
        f"Macro: {resultado['score_macro']:.1f}/10\n\n"
        f"Métricas sin datos: {len(resultado.get('metricas_sin_datos', []))}\n\n"
        + "\n".join(f"- {r}" for r in resultado.get("razones", []))
    )


def _formatear_posicion_abierta(symbol: str, posicion: dict) -> str:
    return (
        f"📈 Paper trading - posición ABIERTA\n\n"
        f"{symbol} {posicion['direction']}\n"
        f"Entry: {posicion['entry_price']:.1f}\n"
        f"Stop: {posicion['stop_price']:.1f}\n"
        f"Target: {posicion['target_price']:.1f}\n"
        f"Tamaño: {posicion['size_usdt']:.1f} USDT (simulado, no es dinero real)"
    )


def _formatear_posicion_cerrada(symbol: str, posicion: dict) -> str:
    resultado_emoji = "✅" if posicion["pnl_usdt"] >= 0 else "❌"
    return (
        f"{resultado_emoji} Paper trading - posición CERRADA ({posicion['close_reason']})\n\n"
        f"{symbol} {posicion['direction']}\n"
        f"Entry: {posicion['entry_price']:.1f} -> Close: {posicion['close_price']:.1f}\n"
        f"PnL: {posicion['pnl_usdt']:+.1f} USDT ({posicion['pnl_pct']:+.1f}%) - simulado, no es dinero real"
    )


def notificar(symbol: str, resultado_engine: dict, paper_resultado: dict | None = None) -> list[str]:
    """
    Envía el mensaje detallado de esta corrida (solo si la señal es
    LONG o SHORT - ver activo_es_operable) más los eventos de paper
    trading que hayan ocurrido. Devuelve la lista de mensajes enviados
    (para trazabilidad y para tests, sin depender de si Telegram
    respondió o no).
    """
    enviados = []

    if activo_es_operable(resultado_engine):
        mensaje = _formatear_resumen(symbol, resultado_engine)
        enviar_mensaje_telegram(mensaje)
        enviados.append(mensaje)
        logger.info(f"Notificación de detalle enviada para {symbol} (activo operable)")

    if paper_resultado:
        for cerrada in paper_resultado.get("posiciones_cerradas", []):
            mensaje = _formatear_posicion_cerrada(symbol, cerrada)
            enviar_mensaje_telegram(mensaje)
            enviados.append(mensaje)
            logger.info(f"Notificación de cierre de posición enviada para {symbol}")

        if paper_resultado.get("posicion_abierta"):
            mensaje = _formatear_posicion_abierta(symbol, paper_resultado["posicion_abierta"])
            enviar_mensaje_telegram(mensaje)
            enviados.append(mensaje)
            logger.info(f"Notificación de apertura de posición enviada para {symbol}")

    return enviados
