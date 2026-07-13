"""
RobotinaIA
Core de la aplicación
"""

from datetime import datetime

from app.core.settings import Settings
from app.services.mock_market_data_provider import MockMarketDataProvider


class RobotinaApplication:
    """
    Clase principal de RobotinaIA.
    Controlará el ciclo de vida de toda la aplicación.
    """

    def start(self):

        provider = MockMarketDataProvider()

        symbol = "MINEROS"

        stock = provider.get_stock(symbol)

        print("=" * 60)
        print(f"🤖 {Settings.APP_NAME}")
        print("=" * 60)
        print(f"Versión : {Settings.VERSION}")
        print(f"Autor    : {Settings.AUTHOR}")
        print(f"Fecha    : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print("-" * 60)
        print("Mercado")
        print(f"Empresa : {stock.company_name}")
        print(f"Símbolo : {stock.symbol}")
        print(f"Precio  : ${stock.price:,.2f}")
        print("=" * 60)