"""
Proveedor de datos simulado para RobotinaIA.
"""

from app.models.stock import Stock
from app.services.market_data_provider import MarketDataProvider


class MockMarketDataProvider(MarketDataProvider):

    def get_stock(self, symbol: str) -> Stock:

        data = {
            "MINEROS": Stock(
                symbol="MINEROS",
                company_name="Mineros S.A.",
                price=15440.00
            ),
            "ECOPETROL": Stock(
                symbol="ECOPETROL",
                company_name="Ecopetrol S.A.",
                price=1985.00
            ),
            "ISA": Stock(
                symbol="ISA",
                company_name="ISA",
                price=23450.00
            ),
            "GRUPOARGOS": Stock(
                symbol="GRUPOARGOS",
                company_name="Grupo Argos",
                price=18500.00
            ),
        }

        return data.get(
            symbol.upper(),
            Stock(
                symbol=symbol.upper(),
                company_name="Empresa no encontrada",
                price=0.0
            ),
        )