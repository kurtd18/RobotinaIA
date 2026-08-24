"""
Servicio unificado de portfolio: alta, consulta, cierre y trailing
stop, para acciones y cripto por igual - reemplaza los dos caminos
paralelos que existían antes (portfolio.py, usado para acciones y para
la posición manual de BTC-USD; paper_positions, usado por el motor
cripto nuevo), que no se comunicaban entre sí.

Puerto de portfolio.py (add_position, get_open_positions,
sell_position, actualizar_trailing_stop, marcar_alerta_stop,
registrar_decision), agregando asset_class/normalized_symbol y P&L
consciente de comisiones vía FeeConfig. La matemática de trailing stop
es un puerto directo de app.alerts.portfolio_alerts._revisar_trailing_stop
- sin el envío de Telegram, que sigue siendo responsabilidad de la capa
de alertas (Épica 5/7), no de este servicio.

Por ahora, portfolio.py (legacy) sigue funcionando exactamente igual
que antes - este módulo no lo reemplaza todavía en producción, eso es
trabajo de Épica 7. Ninguno de los dos escribe en las columnas del otro
de forma incompatible: las columnas nuevas de asset_class/normalized_symbol
tienen defaults consistentes con lo que la migración de Epic 2/4 ya
backfilleó.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.alerts.portfolio_alerts import TRAILING_STEP_PCT
from app.database.connection import get_connection
from app.services.fee_config import CRYPTO_FEE_CONFIG, STOCK_FEE_CONFIG
from app.services.symbol_normalization import normalizar_symbol

TZ_BOGOTA = ZoneInfo("America/Bogota")

_ASSET_CLASSES_VALIDAS = ("stock", "crypto")
_FEE_CONFIGS = {"stock": STOCK_FEE_CONFIG, "crypto": CRYPTO_FEE_CONFIG}


def _now_str():
    return datetime.now(TZ_BOGOTA).strftime("%Y-%m-%d %H:%M:%S%z")


def add_position(symbol, quantity, buy_price, asset_class, target_price=None, stop_loss=None):
    """Abre una posición para `asset_class` ('stock' o 'crypto'),
    calculando normalized_symbol vía symbol_normalization.py. Devuelve
    el id de la posición, o None si la validación falla (mismo
    contrato que portfolio.py.add_position)."""

    if quantity <= 0 or buy_price <= 0:
        logger.warning(f"{symbol}: cantidad y precio de compra deben ser mayores a 0")
        return None

    if asset_class not in _ASSET_CLASSES_VALIDAS:
        raise ValueError(f"asset_class inválido: {asset_class!r}, usa uno de {_ASSET_CLASSES_VALIDAS}")

    normalized_symbol = normalizar_symbol(symbol, asset_class)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO portfolio (
            symbol, quantity, buy_price, buy_date, target_price, stop_loss,
            status, asset_class, normalized_symbol
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol.upper(), quantity, buy_price, _now_str(), target_price, stop_loss,
            "OPEN", asset_class, normalized_symbol,
        ),
    )

    position_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Posición agregada: {symbol} ({asset_class}, ID {position_id})")

    return position_id


def get_open_positions():
    """Todas las posiciones OPEN, de ambas asset_class, como lista de
    dicts (a diferencia de portfolio.py.get_open_positions, que devuelve
    tuplas posicionales - acá se nombran los campos porque ahora son
    más de los que un llamador razonablemente puede desempacar a mano)."""

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, symbol, quantity, buy_price, buy_date, target_price,
               stop_loss, alerta_stop_enviada, asset_class, normalized_symbol
        FROM portfolio WHERE status = 'OPEN' ORDER BY id
        """
    )
    filas = cursor.fetchall()
    conn.close()

    return [
        {
            "id": f[0], "symbol": f[1], "quantity": f[2], "buy_price": f[3],
            "buy_date": f[4], "target_price": f[5], "stop_loss": f[6],
            "alerta_stop_enviada": f[7], "asset_class": f[8], "normalized_symbol": f[9],
        }
        for f in filas
    ]


def sell_position(position_id, sell_price):
    """Cierra una posición OPEN, calculando P&L a través del FeeConfig
    de su asset_class. Con el FeeConfig por defecto (sin configurar),
    el P&L neto es idéntico a (sell_price - buy_price) * quantity y
    fees_included queda en 0 - exactamente el mismo número que
    portfolio.py.sell_position calculaba antes, más el flag honesto de
    si esas comisiones eran reales o no.

    Devuelve un dict con el resultado, o None si la posición no existe
    o ya está cerrada (mismo contrato que portfolio.py.sell_position)."""

    if sell_price <= 0:
        logger.warning("El precio de venta debe ser mayor a 0.")
        return None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT quantity, buy_price, asset_class FROM portfolio WHERE id = ? AND status = 'OPEN'",
        (position_id,),
    )
    resultado = cursor.fetchone()

    if not resultado:
        logger.warning(f"Posición {position_id} no encontrada o ya está cerrada.")
        conn.close()
        return None

    quantity, buy_price, asset_class = resultado
    gross_pnl = (sell_price - buy_price) * quantity
    profit_pct = ((sell_price - buy_price) / buy_price) * 100

    fee_config = _FEE_CONFIGS[asset_class]
    net_pnl, configured = fee_config.apply(gross_pnl, quantity, sell_price)

    cursor.execute(
        """
        UPDATE portfolio
        SET status='CLOSED', sell_price=?, sell_date=?,
            fee_pct_applied=?, fees_included=?
        WHERE id=?
        """,
        (
            sell_price, _now_str(),
            fee_config.fee_pct if configured else None,
            1 if configured else 0,
            position_id,
        ),
    )

    conn.commit()
    conn.close()
    logger.info(
        f"Posición {position_id} cerrada | P&L: ${net_pnl:,.2f} | "
        f"Rentabilidad: {profit_pct:.2f}% | comisiones incluidas: {configured}"
    )

    return {
        "position_id": position_id,
        "pnl": net_pnl,
        "gross_pnl": gross_pnl,
        "profit_pct": profit_pct,
        "fees_included": 1 if configured else 0,
    }


def actualizar_trailing_stop(position_id, nuevo_stop, nuevo_target):
    """Persiste un nuevo stop_loss/target_price para una posición
    (puerto directo de portfolio.py.actualizar_trailing_stop)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE portfolio SET stop_loss=?, target_price=? WHERE id=?",
        (nuevo_stop, nuevo_target, position_id),
    )

    conn.commit()
    conn.close()

    logger.info(
        f"Posición {position_id}: trailing stop actualizado -> "
        f"stop={nuevo_stop:.2f} objetivo={nuevo_target:.2f}"
    )


def aplicar_trailing_stop(position_id, precio_actual, stop_loss, target_price):
    """Si el precio alcanzó (o superó) el objetivo, sube el stop al
    objetivo anterior y el objetivo un TRAILING_STEP_PCT más (3%),
    persistiendo cada escalón. Si el precio saltó varios niveles de una
    sola vez, aplica todos los escalones que correspondan en el mismo
    llamado (compone correctamente). Devuelve (stop_loss, target_price)
    finales.

    Puerto directo de la matemática de
    app.alerts.portfolio_alerts._revisar_trailing_stop - sin el envío
    de Telegram, que sigue siendo responsabilidad de la capa de
    alertas, no de este servicio.
    """
    while target_price is not None and precio_actual >= target_price:
        nuevo_stop = target_price
        nuevo_target = target_price * (1 + TRAILING_STEP_PCT)

        actualizar_trailing_stop(position_id, nuevo_stop, nuevo_target)

        stop_loss, target_price = nuevo_stop, nuevo_target

    return stop_loss, target_price


def marcar_alerta_stop(position_id, enviada: bool):
    """Marca si ya se envió la alerta de 'toca el stop' para esta
    posición (puerto directo de portfolio.py.marcar_alerta_stop)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE portfolio SET alerta_stop_enviada=? WHERE id=?",
        (1 if enviada else 0, position_id),
    )

    conn.commit()
    conn.close()


def registrar_decision(position_id, decision, precio):
    """Guarda la decisión tomada (MANTENER/VENDER) cuando se tocó el
    stop (puerto directo de portfolio.py.registrar_decision)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO portfolio_decisions (position_id, decision, precio, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (position_id, decision, precio, _now_str()),
    )

    conn.commit()
    conn.close()

    logger.info(f"Posición {position_id}: decisión registrada -> {decision}")
