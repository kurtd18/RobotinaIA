"""
Análisis diario (solo Apertura/Cierre) de los 10 activos BVC, desde enero
hasta hoy: identifica días "caída" (cierre por debajo de la apertura, vela
roja) y cuenta cuántas veces, en los días siguientes, aparece una vela de
recuperación de +3% o más (apertura a cierre del mismo día).

Usa velas DIARIAS (no de 5 minutos) porque Yahoo Finance sí permite pedir
histórico largo (desde enero) para este intervalo, a diferencia de las
velas intradía que están limitadas a 60 días.

Esto es un análisis descriptivo/exploratorio de patrones, no un backtest
de dinero - no simula compras ni comisiones.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_reversion_diaria.py
    python scripts/analisis_reversion_diaria.py --inicio 2026-01-01 --umbral 3.0
"""

import argparse
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = [
    "PFCIBEST.CL",   # Bancolombia Preferencial
    "ECOPETROL.CL",  # Ecopetrol
    "GEB.CL",        # Grupo Energía Bogotá
    "GRUPOARGOS.CL", # Grupo Argos
    "CEMARGOS.CL",   # Cementos Argos
    "CELSIA.CL",     # Celsia
    "GRUPOSURA.CL",  # Grupo Sura
    "PFDAVVNDA.CL",  # Davivienda Preferencial
    "TERPEL.CL",     # Organización Terpel
    "NUTRESA.CL",    # Grupo Nutresa
]

VENTANAS = [1, 2, 3, 5]  # días después de la caída a revisar
UMBRAL_ANOMALIA = 15.0   # % - movimientos diarios más grandes que esto se tratan como
                          # splits de acciones o errores de datos, no movimientos reales


def _cargar_datos_diarios(symbol, fecha_inicio):
    data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    """Excluye días con movimientos absurdos (>15% en un solo día), que
    casi siempre son splits de acciones mal ajustados por Yahoo Finance o
    errores de datos, no movimientos reales del mercado."""

    variacion_dia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_dia.abs() > UMBRAL_ANOMALIA]

    if len(anomalos) > 0:
        print(f"  ⚠️  {len(anomalos)} día(s) excluido(s) por movimiento anómalo "
              f"(probable split, no un movimiento real):")
        for fecha in anomalos:
            print(f"      {fecha.strftime('%Y-%m-%d')}: {variacion_dia.loc[fecha]:+.2f}%")

    return data.drop(index=anomalos)


def _analizar(data, umbral):
    variacion_dia = ((data["Close"] - data["Open"]) / data["Open"]) * 100

    total_dias = len(data)
    dias_rojos = int((variacion_dia < 0).sum())
    dias_verdes = total_dias - dias_rojos
    variacion_promedio = float(variacion_dia.mean())

    idx_caidas = [i for i in range(total_dias) if variacion_dia.iloc[i] < 0]

    resultados_ventana = {}
    for ventana in VENTANAS:
        casos = 0
        aciertos = 0
        for i in idx_caidas:
            fin = min(i + 1 + ventana, total_dias)
            futuros = variacion_dia.iloc[i + 1: fin]
            if len(futuros) == 0:
                continue
            casos += 1
            if (futuros >= umbral).any():
                aciertos += 1
        tasa = (aciertos / casos * 100) if casos else 0.0
        resultados_ventana[ventana] = (casos, aciertos, tasa)

    return {
        "total_dias": total_dias,
        "dias_rojos": dias_rojos,
        "dias_verdes": dias_verdes,
        "variacion_promedio": variacion_promedio,
        "resultados_ventana": resultados_ventana,
    }


def correr(fecha_inicio, umbral):
    print(f"Análisis diario (Apertura/Cierre) desde {fecha_inicio} hasta hoy")
    print(f"'Caída' = día que cierra por debajo de su apertura (vela roja)")
    print(f"'Recuperación' = vela de +{umbral}% o más (apertura a cierre del mismo día)")
    print()

    resumen_general = {v: [0, 0] for v in VENTANAS}

    for symbol in ACTIVOS:
        print("=" * 90)
        print(symbol)
        print("=" * 90)

        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < 10:
            print("  Sin datos suficientes.")
            print()
            continue

        data = _filtrar_anomalias(data)

        r = _analizar(data, umbral)

        variacion_dia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
        top_movimientos = variacion_dia.abs().nlargest(3)

        print(f"  Rango de datos: {data.index[0].strftime('%Y-%m-%d')} a "
              f"{data.index[-1].strftime('%Y-%m-%d')} ({r['total_dias']} días de trading)")
        print(f"  Días rojos (caída): {r['dias_rojos']} | Días verdes: {r['dias_verdes']} | "
              f"Variación promedio diaria: {r['variacion_promedio']:+.2f}%")
        print(f"  Los 3 movimientos diarios más extremos (para detectar datos anómalos):")
        for fecha, valor in top_movimientos.items():
            valor_real = variacion_dia.loc[fecha]
            print(f"    {fecha.strftime('%Y-%m-%d')}: {valor_real:+.2f}% "
                  f"(Open={data.loc[fecha, 'Open']:,.2f} Close={data.loc[fecha, 'Close']:,.2f})")
        print()
        print(f"  Después de una caída, ¿aparece una vela de +{umbral}% dentro de...?")

        for ventana, (casos, aciertos, tasa) in r["resultados_ventana"].items():
            print(f"    {ventana} día(s) siguiente(s): {aciertos}/{casos} veces ({tasa:.1f}%)")
            resumen_general[ventana][0] += casos
            resumen_general[ventana][1] += aciertos

        print()

    print("=" * 90)
    print("RESUMEN GENERAL (las 10 acciones juntas)")
    print("=" * 90)

    for ventana in VENTANAS:
        casos, aciertos = resumen_general[ventana]
        tasa = (aciertos / casos * 100) if casos else 0.0
        print(f"  Dentro de {ventana} día(s): {aciertos}/{casos} veces ({tasa:.1f}%)")

    print("=" * 90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    parser.add_argument("--umbral", type=float, default=3.0)
    args = parser.parse_args()

    correr(args.inicio, args.umbral)