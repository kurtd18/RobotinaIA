"""
Análisis de "rachas verdes" para Ecopetrol: cuenta cuántas veces, después
de un día que cierra en rojo (cierre por debajo del cierre del día
anterior), el día siguiente cierra en verde - y cuando eso pasa, mide
cuánto creció el precio en la racha de días consecutivos cerrando cada
vez más alto, hasta que la racha se rompe (un día no supera al anterior).

Ejemplo (tal como lo describió el usuario):
  Día 0 cierra en 2400 (rojo, por debajo del día anterior)
  Día 1 cierra en 2500 (verde, sube)
  Día 2 cierra en 2650 (verde, sube más)
  Día 3 cierra en 2800 (verde, sube más)
  Día 4 cierra más bajo que el día 3 -> la racha termina
  Crecimiento medido: (2800 - 2400) / 2400 = +16.67%

Usa velas DIARIAS (Open/High/Low/Close), comparando cierre contra cierre
del día anterior - no apertura/cierre del mismo día.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_rachas_ecopetrol.py
    python scripts/analisis_rachas_ecopetrol.py --inicio 2026-01-01
    python scripts/analisis_rachas_ecopetrol.py --symbol ECOPETROL.CL
"""

import argparse
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _cargar_datos_diarios(symbol, fecha_inicio):
    data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data, umbral=15.0):
    """Igual que en el análisis de reversión diaria: excluye días con un
    salto absurdo (probable split de acciones), usando apertura/cierre del
    mismo día como referencia de sanidad."""

    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > umbral]

    if len(anomalos) > 0:
        print(f"⚠️  {len(anomalos)} día(s) excluido(s) por movimiento anómalo (probable split):")
        for fecha in anomalos:
            print(f"    {fecha.strftime('%Y-%m-%d')}: {variacion_intradia.loc[fecha]:+.2f}%")

    return data.drop(index=anomalos)


def _encontrar_rachas(data):
    """Recorre los cierres día por día, buscando: día rojo (cierre < cierre
    anterior) seguido de un día verde (cierre > cierre del día rojo), y
    mide la racha de días consecutivos cerrando cada vez más alto."""

    cierres = data["Close"].values
    fechas = data.index
    n = len(cierres)

    rachas = []
    total_dias_rojos = 0

    i = 1
    while i < n:
        es_rojo = cierres[i] < cierres[i - 1]

        if not es_rojo:
            i += 1
            continue

        total_dias_rojos += 1

        # ¿El día siguiente (i+1) cierra verde respecto al día rojo (i)?
        if i + 1 >= n or cierres[i + 1] <= cierres[i]:
            i += 1
            continue

        # Sí hay racha verde - medirla mientras cada día supere al anterior
        precio_inicio = cierres[i]  # el cierre del día ROJO (punto de partida)
        fecha_inicio_racha = fechas[i]

        j = i + 1
        while j + 1 < n and cierres[j + 1] > cierres[j]:
            j += 1

        precio_pico = cierres[j]
        fecha_pico = fechas[j]
        dias_de_racha = j - i  # cantidad de días verdes consecutivos
        crecimiento_pct = ((precio_pico - precio_inicio) / precio_inicio) * 100

        rachas.append({
            "fecha_rojo": fechas[i],
            "precio_rojo": precio_inicio,
            "fecha_pico": fecha_pico,
            "precio_pico": precio_pico,
            "dias_de_racha": dias_de_racha,
            "crecimiento_pct": crecimiento_pct,
        })

        i = j + 1  # continuar después del final de esta racha

    return rachas, total_dias_rojos


def correr(symbol, fecha_inicio):
    data = _cargar_datos_diarios(symbol, fecha_inicio)

    if data is None or len(data) < 10:
        print(f"Sin datos suficientes para {symbol}.")
        return

    data = _filtrar_anomalias(data)

    print(f"\n{symbol}")
    print("=" * 100)
    print(f"Rango de datos: {data.index[0].strftime('%Y-%m-%d')} a {data.index[-1].strftime('%Y-%m-%d')} "
          f"({len(data)} días de trading)")
    print()

    rachas, total_dias_rojos = _encontrar_rachas(data)

    print(f"Total de días rojos (cierre < cierre del día anterior): {total_dias_rojos}")
    print(f"De esos, cuántas veces el día siguiente cerró en verde y arrancó una racha: {len(rachas)} "
          f"({(len(rachas) / total_dias_rojos * 100) if total_dias_rojos else 0:.1f}%)")
    print()

    if not rachas:
        print("No se encontraron rachas verdes después de un día rojo.")
        return

    print("-" * 100)
    print(f"{'FECHA ROJO':12} {'PRECIO':>12} {'->':^4} {'FECHA PICO':12} {'PRECIO PICO':>12} "
          f"{'DÍAS':>6} {'CRECIMIENTO':>13}")
    print("-" * 100)

    for r in rachas:
        print(f"{r['fecha_rojo'].strftime('%Y-%m-%d'):12} {r['precio_rojo']:>12,.2f} {'->':^4} "
              f"{r['fecha_pico'].strftime('%Y-%m-%d'):12} {r['precio_pico']:>12,.2f} "
              f"{r['dias_de_racha']:>6} {r['crecimiento_pct']:>+12.2f}%")

    print("-" * 100)

    crecimientos = [r["crecimiento_pct"] for r in rachas]
    dias = [r["dias_de_racha"] for r in rachas]

    print(f"Crecimiento promedio de la racha: {sum(crecimientos) / len(crecimientos):+.2f}%")
    print(f"Crecimiento máximo: {max(crecimientos):+.2f}% | mínimo: {min(crecimientos):+.2f}%")
    print(f"Duración promedio de la racha: {sum(dias) / len(dias):.1f} días")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="ECOPETROL.CL")
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    args = parser.parse_args()

    correr(args.symbol, args.inicio)