class AlertEngine:

    def get_recommendation(self, score: int) -> str:

        if score <= 50:
            return "NO COMPRAR"

        if score <= 75:
            return "REVISAR"

        return "OPORTUNIDAD"