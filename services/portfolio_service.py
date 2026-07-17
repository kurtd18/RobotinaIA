"""
Servicio para administrar el portafolio.
"""

from app.models.portfolio import Portfolio
from app.models.position import Position


class PortfolioService:

    def __init__(self):
        self.portfolio = Portfolio()

    def add_position(
        self,
        symbol: str,
        quantity: int,
        average_price: float,
    ):

        position = Position(
            symbol=symbol,
            quantity=quantity,
            average_price=average_price,
        )

        self.portfolio.add_position(position)

    def get_positions(self):
        return self.portfolio.positions