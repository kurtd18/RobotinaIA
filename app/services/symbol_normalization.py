"""
Mapeo compartido de símbolos "por proveedor" a un símbolo normalizado
único por activo, para que la migración de unificación de portfolio
(Épica 4) y portfolio_service.py usen exactamente el mismo mapeo - no
cada uno el suyo.

Cripto: se deriva quitando el sufijo conocido - "-USD" para símbolos
estilo Yahoo (Settings.ACTIVOS_CRIPTO: "BTC-USD", "ETH-USD", "SOL-USD")
o "USDT" para símbolos estilo Binance (SIMBOLOS_SOPORTADOS: "BTCUSDT",
"ETHUSDT", ...). Así "BTC-USD" y "BTCUSDT" normalizan al mismo "BTC".

Acciones: normalized_symbol es el símbolo tal cual (ej. "ECOPETROL.CL",
"AAPL") - no hay dos proveedores con formatos distintos para el mismo
activo en el universo de acciones actual.
"""

_SUFIJOS_CRIPTO_CONOCIDOS = ("-USD", "USDT")


def normalizar_symbol(symbol: str, asset_class: str) -> str:
    """Devuelve el símbolo normalizado para `symbol` según `asset_class`
    ('stock' o 'crypto')."""
    if asset_class == "crypto":
        for sufijo in _SUFIJOS_CRIPTO_CONOCIDOS:
            if symbol.endswith(sufijo):
                return symbol[: -len(sufijo)]
        return symbol  # símbolo cripto sin sufijo reconocido - se deja igual

    return symbol
