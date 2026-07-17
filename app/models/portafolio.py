"""
Modelo del portafolio de inversiones.
"""

from dataclasses import dataclass, field

from app.models.position import Position


@dataclass
class Portfolio:
    positions: list[Position] = field(default_factory=list)

    def add_position(self, position: Position):
        self.positions.append(position)