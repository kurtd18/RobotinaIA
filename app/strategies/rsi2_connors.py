"""
Estrategia de producción: RSI(2) de Larry Connors ("Short Term Trading
Strategies That Work", Connors & Alvarez, 2008) - el hallazgo con la
evidencia más sólida y consistente de toda la investigación de la
sesión, validado con calibración/validación fuera de muestra en 4
ventanas de tiempo distintas (2018, 2023, 2024, 2025), todas con la
señal ganándole al azar.

Señal de ENTRADA (compra): precio de cierre por encima de la SMA200, y
el RSI(2) cruza por debajo de 5 (el momento exacto, no cada día que se
mantiene ahí).

Señal de SALIDA (venta): el RSI(2) cruza por encima de 70, o el precio
cae por debajo de la SMA200 (se pierde el filtro de tendencia) - lo que
ocurra primero.

Corre UNA VEZ AL DÍA (a diferencia del scoring anterior, que corría cada
15 minutos con velas de 5 minutos - el RSI(2) de Connors usa velas
DIARIAS, así que no tiene sentido revisarlo más de una vez al día; el
resultado de "hoy" no cambia hasta que cierre la vela de mañana).

Universo: acciones BVC + internacional + ETF (sin cripto - la
investigación de la sesión mostró que esta señal específica no se
traslada bien a cripto en escalas de tiempo intradía).

No coloca dinero real ni ejecuta órdenes - solo envía alertas por
Telegram, igual que el sistema anterior.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas_ta as ta
import yfinance as yf

from loguru import logger

from app.core.settings import Settings
from app.database import (
    guardar_senal,
    existe_senal_pendiente,
    obtener_senal_pendiente_por_symbol,
    marcar_senal_vendida,
)
from app.services.telegram_service import enviar_mensaje_telegram

TZ_BOGOTA = ZoneInfo("America/Bogota")

_CRIPTOS_A_EXCLUIR = {"BTC-USD", "ETH-USD", "SOL-USD"}
ACTIVOS = [a for a in Settings.todos_los_activos() if a not in _CRIPTOS_A_EXCLUIR]

RSI_PERIODO = 2
RSI_ENTRADA = 5.0
RSI_SALIDA = 70.0
SMA_PERIODO = 200

PERIODO_DESCARGA = "2y"  # suficiente para SMA200 con margen, sin descargar años innecesarios
UMBRAL_ANOMALIA = 15.0


def _cargar_datos_diarios(symbol):
    try:
        data = yf.Ticker(symbol).history(period=PERIODO_DESCARGA, interval="1d")
    except Exception:
        logger.exception(f"{symbol}: error descargando datos")
        return None

    if data.empty:
        return None

    return data


def _limpiar_datos(data):
    """Mismas 3 capas de limpieza validadas durante la investigación:
    quitar velas con datos faltantes, velas fantasma de volumen cero
    (festivos que Yahoo Finance rellena en vez de omitir), y saltos de
    precio absurdos de un solo día (splits mal ajustados)."""

    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    data = data[data["Volume"] > 0]

    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_indicadores(data):
    """Calcula RSI(2) y SMA200 sobre toda la serie. Devuelve (rsi, sma)
    o (None, None) si no se pudieron calcular (datos insuficientes o
    degenerados para ese activo en particular)."""

    close = data["Close"]
    rsi = ta.rsi(close, length=RSI_PERIODO)
    sma = ta.sma(close, length=SMA_PERIODO)

    if rsi is None or sma is None:
        return None, None

    return rsi, sma


def _hubo_cruce_entrada_hoy(data, rsi, sma):
    """¿El día más reciente cumple la condición de entrada? (precio >
    SMA200, y el RSI(2) cruzó por debajo de 5 respecto al día anterior)."""

    if len(data) < 2:
        return False

    rsi_hoy = rsi.iloc[-1]
    rsi_ayer = rsi.iloc[-2]
    sma_hoy = sma.iloc[-1]
    precio_hoy = data["Close"].iloc[-1]

    if rsi_hoy != rsi_hoy or rsi_ayer != rsi_ayer or sma_hoy != sma_hoy:
        return False

    tendencia_alcista = precio_hoy > sma_hoy
    cruzo_a_sobreventa = rsi_ayer >= RSI_ENTRADA and rsi_hoy < RSI_ENTRADA

    return tendencia_alcista and cruzo_a_sobreventa


def _hubo_condicion_salida_hoy(data, rsi, sma):
    """¿El día más reciente cumple la condición de salida? (RSI(2) por
    encima de 70, o el precio cayó bajo la SMA200)."""

    if len(data) < 1:
        return False

    rsi_hoy = rsi.iloc[-1]
    sma_hoy = sma.iloc[-1]
    precio_hoy = data["Close"].iloc[-1]

    if rsi_hoy != rsi_hoy or sma_hoy != sma_hoy:
        return False

    return rsi_hoy > RSI_SALIDA or precio_hoy < sma_hoy


def _enviar_alerta_compra(activo, precio, rsi_valor, ahora):
    mensaje = f"""
🤖 ROBOTINAIA - RSI(2) Connors

🟢 SEÑAL DE COMPRA

📈 Activo: {activo}
💲 Precio: {precio:,.2f}
📊 RSI(2): {rsi_valor:.2f} (< {RSI_ENTRADA:.0f}, precio sobre SMA{SMA_PERIODO})
🕒 Fecha: {ahora.strftime('%Y-%m-%d')}

Estrategia: RSI(2) de Larry Connors - validada con evidencia consistente
en 4 ventanas de tiempo distintas durante la investigación.

Esto es una alerta informativa, no una orden automática.
"""
    codigo = enviar_mensaje_telegram(mensaje)
    logger.info(f"{activo} -> ALERTA DE COMPRA enviada (Telegram: {codigo})")


def _enviar_alerta_venta(activo, precio_entrada, fecha_entrada, precio_salida, motivo, ahora):
    variacion_pct = ((precio_salida - precio_entrada) / precio_entrada) * 100
    emoji_resultado = "✅" if variacion_pct > 0 else "🔴"

    mensaje = f"""
🤖 ROBOTINAIA - RSI(2) Connors

🔴 SEÑAL DE VENTA

📈 Activo: {activo}
💲 Precio de entrada: {precio_entrada:,.2f}
🕒 Fecha de entrada: {fecha_entrada}
💲 Precio de salida: {precio_salida:,.2f}
{emoji_resultado} Resultado: {variacion_pct:+.2f}%
📋 Motivo: {motivo}
🕒 Fecha de salida: {ahora.strftime('%Y-%m-%d')}

Esto es una alerta informativa, no una orden automática.
"""
    codigo = enviar_mensaje_telegram(mensaje)
    logger.info(f"{activo} -> ALERTA DE VENTA enviada ({variacion_pct:+.2f}%, Telegram: {codigo})")


def procesar_activo(activo, ahora):
    data = _cargar_datos_diarios(activo)
    if data is None or len(data) < SMA_PERIODO + 5:
        logger.warning(f"{activo}: sin datos suficientes")
        return

    data = _limpiar_datos(data)
    if len(data) < SMA_PERIODO + 5:
        logger.warning(f"{activo}: sin datos suficientes tras la limpieza")
        return

    rsi, sma = _calcular_indicadores(data)
    if rsi is None:
        logger.warning(f"{activo}: no se pudieron calcular los indicadores")
        return

    precio_hoy = float(data["Close"].iloc[-1])
    rsi_hoy = float(rsi.iloc[-1]) if rsi.iloc[-1] == rsi.iloc[-1] else None

    senal_pendiente = obtener_senal_pendiente_por_symbol(activo)

    if senal_pendiente is None:
        # No hay posición abierta para este activo - revisar si hoy se
        # cumple la condición de entrada.
        if _hubo_cruce_entrada_hoy(data, rsi, sma):
            signal_id = guardar_senal(str(ahora), activo, int(rsi_hoy or 0), precio_hoy)
            _enviar_alerta_compra(activo, precio_hoy, rsi_hoy or 0.0, ahora)
        else:
            logger.info(f"{activo}: sin señal (precio={precio_hoy:.2f}, RSI2={rsi_hoy})")
    else:
        # Ya hay una posición abierta - revisar si hoy se cumple la
        # condición de salida.
        signal_id, precio_entrada, fecha_entrada = senal_pendiente

        if _hubo_condicion_salida_hoy(data, rsi, sma):
            sma_hoy = float(sma.iloc[-1])
            motivo = (
                f"RSI(2) cruzó sobre {RSI_SALIDA:.0f}"
                if rsi_hoy is not None and rsi_hoy > RSI_SALIDA
                else f"Precio cayó bajo la SMA{SMA_PERIODO}"
            )
            marcar_senal_vendida(signal_id)
            _enviar_alerta_venta(activo, precio_entrada, fecha_entrada, precio_hoy, motivo, ahora)
        else:
            logger.info(f"{activo}: posición abierta, sin condición de salida todavía")


def ejecutar_rsi2_connors():
    """Punto de entrada del módulo: corre el ciclo diario completo."""

    ahora = datetime.now(TZ_BOGOTA)

    logger.info("=" * 80)
    logger.info(f"ROBOTINAIA - RSI(2) Connors - {ahora}")
    logger.info("=" * 80)

    for activo in ACTIVOS:
        try:
            procesar_activo(activo, ahora)
        except Exception:
            logger.exception(f"{activo}: error procesando la estrategia")

    logger.info("PROCESO FINALIZADO")


if __name__ == "__main__":
    ejecutar_rsi2_connors()