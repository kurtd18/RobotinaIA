from app.services.alert_engine import AlertEngine

engine = AlertEngine()

print(engine.get_recommendation(40))
print(engine.get_recommendation(75))
print(engine.get_recommendation(90))        