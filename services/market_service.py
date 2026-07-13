"""
Servicio de mercado de RobotinaIA.
"""

from app.models.stock import Stock
from app.services.market_data_provider import MarketDataProvider


class MarketService:

    def __init__(self, provider: MarketDataProvider):
        self.provider = provider

    def get_stock(self, symbol: str) -> Stock:
        return self.provider.get_stock(symbol)