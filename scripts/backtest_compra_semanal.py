"""
Simula comprar cada semana el LUNES (a la apertura), y CIERRA el VIERNES
(al cierre) - salvo que antes se cumpla el objetivo (+3%) o el stop
(-1%), en cuyo caso se sale de inmediato ese mismo día.

Es una operación acotada a la semana, no un trailing stop abierto: solo
un objetivo fijo y un stop fijo, con un límite de tiempo (el viernes).

Entrada: apertura del primer día de trading de cada semana.
Salida: la primera de estas 3 cosas que ocurra:
  - El precio toca +3% (objetivo) -> vende ahí
  - El precio toca -1% (stop) -> vende ahí
  - Llega el último día de trading de la semana sin tocar ninguno -> vende
    al cierre de ese día, sea cual sea el resultado

Dinero: desembolso $5,000,000 COP por CADA semana (posiciones
independientes, cada semana es su propia operación).

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_compra_semanal.py
    python scripts/backtest_compra_semanal.py --activos TERPEL.CL,NUTRESA.CL
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS_DEFAULT = [
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

OBJETIVO_PCT = 0.03
STOP_PCT = 0.01

UMBRAL_ANOMALIA = 15.0

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _cargar_datos_diarios(symbol, fecha_inicio):
    data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _agrupar_por_semana(data):
    """Devuelve una lista de listas de índices posicionales, cada una con
    los días de trading de una semana calendario."""

    fechas_naive = data.index.tz_localize(None) if data.index.tz is not None else data.index
    periodos = fechas_naive.to_period("W")

    semanas = []
    semana_actual = []
    periodo_actual = None

    for pos, periodo in enumerate(periodos):
        if periodo != periodo_actual:
            if semana_actual:
                semanas.append(semana_actual)
            semana_actual = []
            periodo_actual = periodo
        semana_actual.append(pos)

    if semana_actual:
        semanas.append(semana_actual)

    return semanas


@dataclass
class Operacion:
    entrada_fecha: object
    entrada_precio: float
    salida_fecha: object
    salida_precio: float
    resultado: str
    variacion_pct: float


def _simular_semana(data, indices_semana):
    """Simula una operación acotada a una sola semana: entra el lunes
    (apertura), sale al tocar objetivo/stop, o al cierre del viernes si
    no se tocó ninguno."""

    idx_lunes = indices_semana[0]
    idx_viernes = indices_semana[-1]

    entrada_precio = float(data["Open"].iloc[idx_lunes])
    entrada_fecha = data.index[idx_lunes]

    objetivo = entrada_precio * (1 + OBJETIVO_PCT)
    stop = entrada_precio * (1 - STOP_PCT)

    for pos in indices_semana:
        vela = data.iloc[pos]
        toco_objetivo = vela["High"] >= objetivo
        toco_stop = vela["Low"] <= stop

        if toco_objetivo and toco_stop:
            return Operacion(entrada_fecha, entrada_precio, data.index[pos], float(stop),
                              "STOP", -STOP_PCT * 100)
        if toco_objetivo:
            return Operacion(entrada_fecha, entrada_precio, data.index[pos], float(objetivo),
                              "OBJETIVO", OBJETIVO_PCT * 100)
        if toco_stop:
            return Operacion(entrada_fecha, entrada_precio, data.index[pos], float(stop),
                              "STOP", -STOP_PCT * 100)

    # No se tocó ninguno en toda la semana - cierra al cierre del viernes
    precio_viernes = float(data["Close"].iloc[idx_viernes])
    variacion_pct = ((precio_viernes - entrada_precio) / entrada_precio) * 100
    return Operacion(entrada_fecha, entrada_precio, data.index[idx_viernes], precio_viernes,
                      "CIERRE_VIERNES", variacion_pct)


def correr(activos, fecha_inicio):
    print(f"Estrategia: compra el LUNES (apertura), objetivo +{OBJETIVO_PCT*100:.0f}% / "
          f"stop -{STOP_PCT*100:.0f}%, cierra el VIERNES si no se tocó ninguno antes")
    print(f"Desembolso: ${DESEMBOLSO_TOTAL:,.0f} COP por semana | Comisión: ${COMISION:,.0f} COP/lado")
    print()

    for symbol in activos:
        print("=" * 100)
        print(symbol)
        print("=" * 100)

        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < 10:
            print("  Sin datos suficientes.")
            print()
            continue

        data = _filtrar_anomalias(data)
        semanas = _agrupar_por_semana(data)

        neto_total = 0.0
        ganaron = 0
        perdieron = 0
        n_objetivo = 0
        n_stop = 0
        n_cierre_viernes = 0

        for indices_semana in semanas:
            op = _simular_semana(data, indices_semana)
            neto = _calcular_dinero(op.variacion_pct)
            neto_total += neto

            if neto > 0:
                ganaron += 1
            else:
                perdieron += 1

            if op.resultado == "OBJETIVO":
                n_objetivo += 1
            elif op.resultado == "STOP":
                n_stop += 1
            else:
                n_cierre_viernes += 1

            print(f"  Lunes {op.entrada_fecha.strftime('%Y-%m-%d')} @ ${op.entrada_precio:,.2f}  ->  "
                  f"{op.salida_fecha.strftime('%Y-%m-%d')} @ ${op.salida_precio:,.2f} | "
                  f"{op.resultado:15} | {op.variacion_pct:+.2f}% | neto {neto:+,.0f} COP")

        print("-" * 100)
        print(f"  Semanas operadas: {len(semanas)} (netas positivas={ganaron} negativas={perdieron})")
        print(f"  Por motivo de salida: objetivo={n_objetivo} | stop={n_stop} | cierre del viernes={n_cierre_viernes}")
        print(f"  Capital total desembolsado: ${len(semanas) * DESEMBOLSO_TOTAL:,.0f} COP")
        print(f"  Resultado neto de {symbol}: ${neto_total:+,.0f} COP")
        if semanas:
            print(f"  Neto promedio por semana: ${neto_total/len(semanas):+,.0f} COP")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activos", type=str, default=",".join(ACTIVOS_DEFAULT))
    parser.add_argument("--inicio", type=str, default="2026-01-01")
    args = parser.parse_args()

    activos = args.activos.split(",")

    correr(activos, args.inicio)