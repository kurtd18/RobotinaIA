"""
Representa una posición dentro del portafolio.
"""

from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    quantity: int
    average_price: float