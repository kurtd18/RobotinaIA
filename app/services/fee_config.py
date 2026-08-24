"""
Estrategia de comisiones para el cálculo de P&L unificado (Épica 4).

fee_pct=0.0 NO significa "sin comisiones": significa "comisiones no
configuradas todavía" (configured=False). Configurar una tasa real es
una decisión del operador con datos reales de su bróker/exchange, fuera
del alcance de este blueprint (ver §1 No-Goals) - acá solo se construye
la interfaz de estrategia para que esa decisión, cuando se tome, no
requiera reescribir portfolio_service.py, y para que un P&L nunca se
presente como "neto de comisiones" cuando en realidad no lo es.
"""

from abc import ABC, abstractmethod


class FeeConfig(ABC):
    """Interfaz de estrategia de comisiones."""

    @abstractmethod
    def apply(self, gross_pnl: float, quantity: float, price: float) -> tuple[float, bool]:
        """
        Recibe el P&L bruto de una operación y devuelve
        (p&l neto de comisiones, si las comisiones estaban configuradas).

        El segundo valor (`configured`) es la señal honesta: False
        significa que el primer valor es simplemente el P&L bruto sin
        tocar, no un P&L "neto" de verdad.
        """


class FlatPercentageFeeConfig(FeeConfig):
    """Comisión como un porcentaje plano sobre el valor de la operación
    (quantity * price), descontado del P&L bruto.

    fee_pct=0.0 con configured=False (los valores por defecto) es el
    estado "no configurado todavía" - no "cero comisiones reales". El
    futuro que reemplace esto por spread/comisión fija/impuestos es otra
    subclase de FeeConfig, no un cambio a esta clase.
    """

    def __init__(self, fee_pct: float = 0.0, configured: bool = False):
        if fee_pct < 0:
            raise ValueError(f"fee_pct no puede ser negativo: {fee_pct}")
        self.fee_pct = fee_pct
        self.configured = configured

    def apply(self, gross_pnl: float, quantity: float, price: float) -> tuple[float, bool]:
        valor_operacion = quantity * price
        comision = valor_operacion * self.fee_pct
        return gross_pnl - comision, self.configured


# Instancias módulo-nivel que usa app/services/portfolio_service.py
# (E4-T3). Ambas sin configurar por defecto - ver docstring del módulo.
# Cuando haya tasas reales, se reconstruyen acá con configured=True, no
# se inventan en portfolio_service.py.
STOCK_FEE_CONFIG = FlatPercentageFeeConfig()
CRYPTO_FEE_CONFIG = FlatPercentageFeeConfig()
