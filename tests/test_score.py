from app.services.score_engine import ScoreEngine

engine = ScoreEngine()

score = engine.calculate(
    ema_ok=True,
    rsi_ok=True,
    macd_ok=True,
    volume_ok=False
)

print(f"Score: {score}")
