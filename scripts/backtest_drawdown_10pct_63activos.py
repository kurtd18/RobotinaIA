"""
Para un conjunto de activos específico, muestra por cada operación de la
señal "drawdown -10% + trailing stop": cuántos días tardó en cruzar a
terreno positivo por primera vez (el precio superó el de entrada), y
cuántos días duró en total hasta la salida real.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/analisis_tiempo_profit.py
    python scripts/analisis_tiempo_profit.py --inicio 2025-01-01
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTIVOS = [
    "MINEROS.CL", "FABRICATO.CL", "ECOPETROL.CL", "NUTRESA.CL", "PFGRUPSURA.CL",
    "F", "PFAVAL.CL", "ENKA.CL", "NU", "OCCIDENTE.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
]

UMBRAL_ANOMALIA = 15.0
VENTANA_MAXIMO = 20
INCREMENTO_PCT = 0.01

STOP_INICIAL_PCT = 0.05
OBJETIVO_INICIAL_PCT = 0.08

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _cargar_datos_diarios(symbol, fecha_inicio):
    try:
        data = yf.Ticker(symbol).history(start=fecha_inicio, interval="1d")
    except Exception:
        return None
    if data.empty:
        return None
    return data


def _filtrar_anomalias(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    # Excluir velas fantasma: volumen cero (días sin negociación real, como
    # festivos, que Yahoo Finance rellena con un valor plano en vez de omitir)
    data = data[data["Volume"] > 0]
    variacion_intradia = ((data["Close"] - data["Open"]) / data["Open"]) * 100
    anomalos = data.index[variacion_intradia.abs() > UMBRAL_ANOMALIA]
    return data.drop(index=anomalos)


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_drawdown(data, ventana_maximo, umbral_drawdown):
    maximo_reciente = data["Close"].rolling(ventana_maximo).max().shift(1)
    drawdown_pct = -((data["Close"] - maximo_reciente) / maximo_reciente * 100)

    cruces = []
    for i in range(ventana_maximo + 1, len(data)):
        dd_hoy = drawdown_pct.iloc[i]
        dd_ayer = drawdown_pct.iloc[i - 1]
        if dd_hoy != dd_hoy or dd_ayer != dd_ayer:
            continue
        if dd_ayer < umbral_drawdown and dd_hoy >= umbral_drawdown:
            cruces.append(i)

    return cruces


@dataclass
class OperacionConTiempo:
    entrada_fecha: object
    entrada_precio: float
    dias_hasta_positivo: object  # None si nunca cruzó a positivo
    dias_hasta_salida: int
    resultado: str
    variacion_pct: float
    neto: float


def _simular_con_tiempos(data, idx_entrada, entrada_precio):
    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + OBJETIVO_INICIAL_PCT)

    n = len(data)
    dias_hasta_positivo = None

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]
        close = data["Close"].iloc[i]

        if dias_hasta_positivo is None and close > entrada_precio:
            dias_hasta_positivo = i - idx_entrada

        if low <= stop:
            return float(stop), data.index[i], i - idx_entrada, dias_hasta_positivo

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + INCREMENTO_PCT)

    precio_final = float(data["Close"].iloc[-1])
    return precio_final, data.index[-1], n - 1 - idx_entrada, dias_hasta_positivo


def _simular_operaciones(data, indices_entrada):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        salida_precio, salida_fecha, dias_hasta_salida, dias_hasta_positivo = _simular_con_tiempos(
            data, idx_entrada, entrada_precio
        )

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        variacion_pct = ((salida_precio - entrada_precio) / entrada_precio) * 100
        neto = _calcular_dinero(variacion_pct)
        resultado = "GANO" if neto > 0 else "PERDIO"

        operaciones.append(OperacionConTiempo(
            entrada_fecha=entrada_fecha, entrada_precio=entrada_precio,
            dias_hasta_positivo=dias_hasta_positivo, dias_hasta_salida=dias_hasta_salida,
            resultado=resultado, variacion_pct=variacion_pct, neto=neto,
        ))

        en_posicion_hasta_idx = idx_salida

    return operaciones


def correr(fecha_inicio):
    print(f"Activos: {', '.join(ACTIVOS)}")
    print(f"Período: desde {fecha_inicio}")
    print(f"Señal: drawdown -10%+ | Salida: trailing stop -5%/+8%/+1%")
    print()

    todas_las_operaciones = []

    for symbol in ACTIVOS:
        data = _cargar_datos_diarios(symbol, fecha_inicio)
        if data is None or len(data) < VENTANA_MAXIMO + 20:
            print(f"{symbol}: sin datos suficientes")
            continue

        data = _filtrar_anomalias(data)
        cruces = _detectar_cruces_drawdown(data, VENTANA_MAXIMO, 10.0)
        operaciones = _simular_operaciones(data, cruces)

        if not operaciones:
            print(f"{symbol}: sin operaciones en este período")
            continue

        print(f"=== {symbol} ===")
        for op in operaciones:
            dias_pos_str = f"{op.dias_hasta_positivo} días" if op.dias_hasta_positivo is not None else "nunca"
            print(f"  {op.entrada_fecha.strftime('%Y-%m-%d')} @ ${op.entrada_precio:,.2f} | "
                  f"cruzó a positivo en: {dias_pos_str} | duró en total: {op.dias_hasta_salida} días | "
                  f"{op.resultado} ({op.variacion_pct:+.2f}%) | neto {op.neto:+,.0f} COP")
            todas_las_operaciones.append(op)
        print()

    print("=" * 100)
    print("RESUMEN DE TIEMPOS (las 12 acciones juntas)")
    print("=" * 100)

    ganadoras = [op for op in todas_las_operaciones if op.resultado == "GANO"]
    perdedoras = [op for op in todas_las_operaciones if op.resultado == "PERDIO"]

    dias_positivo_validos = [op.dias_hasta_positivo for op in todas_las_operaciones if op.dias_hasta_positivo is not None]
    nunca_positivo = sum(1 for op in todas_las_operaciones if op.dias_hasta_positivo is None)

    if dias_positivo_validos:
        print(f"Días promedio hasta cruzar a positivo por primera vez: "
              f"{sum(dias_positivo_validos)/len(dias_positivo_validos):.1f} días "
              f"(mínimo {min(dias_positivo_validos)}, máximo {max(dias_positivo_validos)})")
    print(f"Operaciones que NUNCA cruzaron a positivo: {nunca_positivo}/{len(todas_las_operaciones)}")

    dias_salida_ganadoras = [op.dias_hasta_salida for op in ganadoras]
    dias_salida_perdedoras = [op.dias_hasta_salida for op in perdedoras]

    if dias_salida_ganadoras:
        print(f"Días promedio hasta la salida (ganadoras): "
              f"{sum(dias_salida_ganadoras)/len(dias_salida_ganadoras):.1f} días")
    if dias_salida_perdedoras:
        print(f"Días promedio hasta la salida (perdedoras): "
              f"{sum(dias_salida_perdedoras)/len(dias_salida_perdedoras):.1f} días")

    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, default="2025-01-01")
    args = parser.parse_args()

    correr(args.inicio)