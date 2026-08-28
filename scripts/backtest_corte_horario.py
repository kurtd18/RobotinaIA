"""
Simula qué activos habrían cumplido el umbral de señal a una hora de corte
específica (usando solo datos disponibles hasta ese momento, sin ver el
futuro), y compara contra el precio de cierre real del día.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura,
para análisis.

Uso:
    python scripts/backtest_corte_horario.py                  -> hoy, corte 10:00
    python scripts/backtest_corte_horario.py 10:00
    python scripts/backtest_corte_horario.py 2026-07-28 10:00
"""

import sys
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.settings import Settings
from scoring import calcular_score

TZ_BOGOTA = ZoneInfo("America/Bogota")


def _parsear_argumentos():
    args = sys.argv[1:]
    hoy = datetime.now(TZ_BOGOTA).date()

    if len(args) == 0:
        fecha, hora_corte = hoy, dt_time(10 , 0)
    elif len(args) == 1:
        fecha, hora_corte = hoy, dt_time.fromisoformat(args[0])
    elif len(args) == 2:
        fecha = datetime.strptime(args[0], "%Y-%m-%d").date()
        hora_corte = dt_time.fromisoformat(args[1])
    else:
        print("Uso: python scripts/backtest_corte_horario.py [FECHA] HORA_CORTE")
        sys.exit(1)

    return fecha, hora_corte


def _evaluar_activo(symbol, fecha, hora_corte):
    """Calcula el score que habría tenido el activo justo al momento del
    corte, y el precio de cierre real de ese mismo día. Devuelve None si
    no hay datos suficientes."""

    data = yf.Ticker(symbol).history(period="5d", interval="5m")

    if data.empty:
        return None

    data.index = data.index.tz_convert(TZ_BOGOTA)

    momento_corte = datetime.combine(fecha, hora_corte, tzinfo=TZ_BOGOTA)

    # Datos disponibles HASTA el corte (esto es lo que el sistema real
    # habría visto en ese momento, sin ver nada del futuro)
    data_hasta_corte = data[data.index <= momento_corte]

    if data_hasta_corte.empty:
        return None

    try:
        score_corte, precio_corte = calcular_score(data_hasta_corte)
    except Exception as e:
        print(f"  [{symbol}] error calculando score al corte: {type(e).__name__}: {e}")
        return None         

    # Datos del mismo día calendario, para sacar el precio de cierre real
    data_del_dia = data[data.index.date == fecha]

    if data_del_dia.empty:
        return None

    precio_cierre = float(data_del_dia.iloc[-1]["Close"])
    hora_cierre = data_del_dia.index[-1].strftime("%H:%M")

    variacion_pct = ((precio_cierre - precio_corte) / precio_corte) * 100

    return {
        "symbol": symbol,
        "score_corte": score_corte,
        "precio_corte": precio_corte,
        "precio_cierre": precio_cierre,
        "hora_cierre": hora_cierre,
        "variacion_pct": variacion_pct,
    }


def correr_backtest(fecha, hora_corte):
    activos = Settings.todos_los_activos()

    resultados = []
    sin_datos = []

    print(f"Simulando corte a las {hora_corte.strftime('%H:%M')} del {fecha} "
          f"sobre {len(activos)} activos...")
    print()

    for symbol in activos:
        r = _evaluar_activo(symbol, fecha, hora_corte)
        if r is None:
            sin_datos.append(symbol)
        else:
            resultados.append(r)

    cumplieron = [r for r in resultados if r["score_corte"] >= Settings.UMBRAL_SENAL]
    cumplieron.sort(key=lambda r: r["score_corte"], reverse=True)

    print("=" * 90)
    print(f"ACTIVOS QUE CUMPLÍAN EL UMBRAL (>= {Settings.UMBRAL_SENAL}) A LAS {hora_corte.strftime('%H:%M')}")
    print("=" * 90)

    if not cumplieron:
        print("Ninguno cumplió el umbral a esa hora.")
    else:
        aciertos = 0
        for r in cumplieron:
            llego_al_3pct = r["variacion_pct"] >= 3.0
            if llego_al_3pct:
                aciertos += 1
            marca = "✅ LLEGÓ A +3%" if llego_al_3pct else ""
            print(
                f"{r['symbol']:15} score={r['score_corte']:3} | "
                f"{r['precio_corte']:>12,.2f} -> {r['precio_cierre']:>12,.2f} "
                f"(cierre {r['hora_cierre']}) | {r['variacion_pct']:+.2f}%  {marca}"
            )

        print()
        print(f"Total señales: {len(cumplieron)} | Llegaron a +3%: {aciertos} "
              f"({(aciertos / len(cumplieron) * 100):.1f}%)")

    if sin_datos:
        print()
        print(f"Sin datos suficientes ({len(sin_datos)}): {', '.join(sin_datos)}")

    print("=" * 90)


if __name__ == "__main__":
    fecha, hora_corte = _parsear_argumentos()
    correr_backtest(fecha, hora_corte)  