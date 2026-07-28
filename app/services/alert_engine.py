"""
Clasifica un score técnico en una recomendación legible.
"""

from app.core.settings import Settings


class AlertEngine:

    def get_recommendation(self, score: int) -> str:

        if score >= Settings.UMBRAL_SENAL:
            return "OPORTUNIDAD"

        if score >= 50:
            return "REVISAR"

        return "NO COMPRAR"