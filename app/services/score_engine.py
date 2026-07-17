"""
Score Engine.

Calcula el puntaje de una accion.
"""


class ScoreEngine:

    def calculate(
        self,
        ema_ok: bool,
        rsi_ok: bool,
        macd_ok: bool,
        volume_ok: bool
    ) -> int:

        score = 0

        if ema_ok:
            score += 25

        if rsi_ok:
            score += 25

        if macd_ok:
            score += 25

        if volume_ok:
            score += 25

        return score
