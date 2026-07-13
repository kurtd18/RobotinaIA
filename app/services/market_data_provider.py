"""
Contrato para cualquier proveedor de datos de mercado.
"""

from abc import ABC, abstractmethod
from app.models.stock import Stock


class MarketDataProvider(ABC):

    @abstractmethod
    def get_stock(self, symbol: str) -> Stock:
        """
        Retorna toda la información de una acción.
        """
        pass