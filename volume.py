import yfinance as yf

data = yf.Ticker(
    "MINEROS.CL"
).history(
    period="5d",
    interval="5m"
)

# Volumen promedio ultimas 20 velas
data["VOL_AVG"] = (
    data["Volume"]
    .rolling(20)
    .mean()
)

ultimo = data.iloc[-1]

volumen_actual = ultimo["Volume"]
volumen_promedio = ultimo["VOL_AVG"]

print("=" * 60)

print(f"Volumen actual   : {volumen_actual:.0f}")
print(f"Volumen promedio : {volumen_promedio:.0f}")

print("=" * 60)

if volumen_actual > volumen_promedio:

    print("SENAL VOLUMEN: ALTO")

else:

    print("SENAL VOLUMEN: BAJO")