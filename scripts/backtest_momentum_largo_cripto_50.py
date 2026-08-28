"""
Prueba la estrategia de momentum/continuación EN LARGO (comprar tras una
subida fuerte, apostando a que continúe) sobre las 50 criptos del top de
capitalización, velas de 4 horas, 2026 - la imagen espejo de
backtest_short_cripto_4h.py, pero comprando en vez de shortear, y con el
universo ampliado de 50 en vez de 9.

Señal de entrada: el run-up (subida desde el mínimo de 20 velas) cruza el
percentil 75 propio de cada activo.

Salida: trailing stop real normal (no invertido) - stop inicial -5%,
objetivo inicial +8%, incrementos de +1%.

No modifica la base de datos ni envía nada a Telegram - es de solo lectura.

Uso:
    python scripts/backtest_momentum_largo_cripto_50.py
"""

import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.binance_data import obtener_klines

CRIPTOS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "TRXUSDT",
    "DOGEUSDT", "ADAUSDT", "BCHUSDT", "LINKUSDT", "XLMUSDT", "CROUSDT",
    "SUIUSDT", "AVAXUSDT", "SHIBUSDT", "LTCUSDT", "DOTUSDT", "HBARUSDT",
    "UNIUSDT", "AAVEUSDT", "NEARUSDT", "APTUSDT", "ICPUSDT", "ETCUSDT",
    "PEPEUSDT", "TAOUSDT", "RENDERUSDT", "ONDOUSDT", "FETUSDT", "ARBUSDT",
    "ATOMUSDT", "FILUSDT", "OPUSDT", "IMXUSDT", "INJUSDT", "VETUSDT",
    "ALGOUSDT", "GRTUSDT", "SEIUSDT", "STXUSDT", "THETAUSDT", "RUNEUSDT",
    "MKRUSDT", "QNTUSDT", "LDOUSDT", "TIAUSDT", "WLDUSDT", "JUPUSDT",
    "HYPEUSDT", "XMRUSDT",
]

FECHA_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)
VENTANA_MINIMO = 20  # velas de 4h

STOP_INICIAL_PCT = 0.05
OBJETIVO_INICIAL_PCT = 0.08
INCREMENTO_PCT = 0.01

DESEMBOLSO_TOTAL = 5_000_000
COMISION = 7_000


def _limpiar_datos(data):
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    return data[data["Volume"] > 0]


def _calcular_dinero(variacion_pct):
    monto_real = DESEMBOLSO_TOTAL - COMISION
    bruto = monto_real * (1 + variacion_pct / 100)
    neto_recibido = bruto - COMISION
    return neto_recibido - DESEMBOLSO_TOTAL


def _detectar_cruces_runup(data, ventana_minimo, umbral_runup):
    minimo_reciente = data["Close"].rolling(ventana_minimo).min().shift(1)
    runup_pct = (data["Close"] - minimo_reciente) / minimo_reciente * 100

    cruces = []
    for i in range(ventana_minimo + 1, len(data)):
        ru_hoy = runup_pct.iloc[i]
        ru_ayer = runup_pct.iloc[i - 1]

        if ru_hoy != ru_hoy or ru_ayer != ru_ayer:
            continue

        if ru_ayer < umbral_runup and ru_hoy >= umbral_runup:
            cruces.append(i)

    return cruces


def _simular_trailing_stop(data, idx_entrada, entrada_precio):
    """Trailing stop normal (largo): stop abajo, objetivo arriba."""

    stop = entrada_precio * (1 - STOP_INICIAL_PCT)
    objetivo = entrada_precio * (1 + OBJETIVO_INICIAL_PCT)

    n = len(data)

    for i in range(idx_entrada + 1, n):
        low = data["Low"].iloc[i]
        high = data["High"].iloc[i]

        if low <= stop:
            variacion_pct = ((stop - entrada_precio) / entrada_precio) * 100
            return variacion_pct, data.index[i]

        while high >= objetivo:
            stop = objetivo
            objetivo = objetivo * (1 + INCREMENTO_PCT)

    precio_final = float(data["Close"].iloc[-1])
    variacion_pct = ((precio_final - entrada_precio) / entrada_precio) * 100
    return variacion_pct, data.index[-1]


@dataclass
class Operacion:
    symbol: str
    entrada_fecha: object
    entrada_precio: float
    variacion_pct: float
    neto: float


def _simular_operaciones(symbol, data, indices_entrada):
    operaciones = []
    en_posicion_hasta_idx = -1

    for idx_entrada in indices_entrada:
        if idx_entrada <= en_posicion_hasta_idx:
            continue

        entrada_precio = float(data["Close"].iloc[idx_entrada])
        entrada_fecha = data.index[idx_entrada]

        variacion_pct, salida_fecha = _simular_trailing_stop(data, idx_entrada, entrada_precio)

        idx_salida = data.index.get_loc(salida_fecha)
        if isinstance(idx_salida, slice):
            idx_salida = idx_salida.start

        neto = _calcular_dinero(variacion_pct)

        operaciones.append(Operacion(symbol, entrada_fecha, entrada_precio, variacion_pct, neto))
        en_posicion_hasta_idx = idx_salida

    return operaciones


def _generar_aleatorias(symbol, data, cantidad, semilla, minimo_idx):
    random.seed(semilla)
    indices = list(range(minimo_idx, len(data) - 1))
    if not indices or cantidad == 0:
        return []
    indices_random = [random.choice(indices) for _ in range(cantidad)]
    return _simular_operaciones(symbol, data, sorted(set(indices_random)))


def correr():
    print(f"Estrategia LARGA (momentum/continuación): {len(CRIPTOS)} criptos, velas de 4h, "
          f"desde {FECHA_INICIO.strftime('%Y-%m-%d')}")
    print(f"Señal: run-up sobre el percentil 75 propio de cada activo -> COMPRA")
    print(f"Salida: trailing stop (-{STOP_INICIAL_PCT*100:.1f}%/+{OBJETIVO_INICIAL_PCT*100:.1f}%/"
          f"+{INCREMENTO_PCT*100:.0f}%)")
    print()

    todas_calib = []
    todas_valid = []
    datos_por_symbol = {}
    umbrales_por_symbol = {}
    omitidos = []

    for symbol in CRIPTOS:
        try:
            data = obtener_klines(symbol, "4h", FECHA_INICIO)
        except Exception as e:
            omitidos.append(f"{symbol} ({type(e).__name__})")
            continue

        if data is None or len(data) < VENTANA_MINIMO + 30:
            omitidos.append(f"{symbol} (sin datos)")
            continue

        data = _limpiar_datos(data)
        datos_por_symbol[symbol] = data

        minimo_reciente = data["Close"].rolling(VENTANA_MINIMO).min().shift(1)
        runup_pct = (data["Close"] - minimo_reciente) / minimo_reciente * 100
        runups_positivos = runup_pct.dropna()
        runups_positivos = runups_positivos[runups_positivos > 0]
        umbral_runup = float(runups_positivos.quantile(0.75)) if len(runups_positivos) > 0 else 5.0
        umbrales_por_symbol[symbol] = umbral_runup

        cruces = _detectar_cruces_runup(data, VENTANA_MINIMO, umbral_runup)
        operaciones = _simular_operaciones(symbol, data, cruces)

        punto_medio = len(operaciones) // 2
        calib = operaciones[:punto_medio]
        valid = operaciones[punto_medio:]

        neto_symbol = sum(op.neto for op in operaciones)
        print(f"{symbol:10} umbral={umbral_runup:6.2f}% | {len(operaciones):3} operaciones | "
              f"neto ${neto_symbol:+,.0f} COP (calib={len(calib)}, valid={len(valid)})")

        todas_calib.extend(calib)
        todas_valid.extend(valid)

    print()
    if omitidos:
        print(f"Omitidas ({len(omitidos)}): {', '.join(omitidos)}")
        print()

    print("=" * 100)
    print(f"CALIBRACIÓN: {len(todas_calib)} operaciones")
    print("=" * 100)
    if todas_calib:
        neto_calib = sum(op.neto for op in todas_calib)
        ganaron_calib = sum(1 for op in todas_calib if op.neto > 0)
        print(f"Neto total: ${neto_calib:+,.0f} COP | Ganadoras: {ganaron_calib}/{len(todas_calib)} "
              f"({ganaron_calib/len(todas_calib)*100:.1f}%)")

    print()
    print("=" * 100)
    print(f"VALIDACIÓN FUERA DE MUESTRA: {len(todas_valid)} operaciones")
    print("=" * 100)

    if todas_valid:
        neto_valid = sum(op.neto for op in todas_valid)
        ganaron_valid = sum(1 for op in todas_valid if op.neto > 0)
        print(f"Neto total: ${neto_valid:+,.0f} COP | Ganadoras: {ganaron_valid}/{len(todas_valid)} "
              f"({ganaron_valid/len(todas_valid)*100:.1f}%)")

        n_total = 0
        neto_random_total = 0.0
        for symbol, data in datos_por_symbol.items():
            umbral_runup = umbrales_por_symbol[symbol]
            cruces = _detectar_cruces_runup(data, VENTANA_MINIMO, umbral_runup)
            operaciones = _simular_operaciones(symbol, data, cruces)
            punto_medio = len(operaciones) // 2
            n_valid_symbol = len(operaciones) - punto_medio

            aleatorias = _generar_aleatorias(symbol, data, n_valid_symbol, hash(symbol) % 10000, VENTANA_MINIMO)
            neto_random_total += sum(op.neto for op in aleatorias)
            n_total += len(aleatorias)

        print(f"Grupo de control aleatorio (mismo tamaño): {n_total} operaciones | "
              f"neto ${neto_random_total:+,.0f} COP")

        if len(todas_valid) < 30:
            print("⚠️  Muestra menor a 30 - resultado indicativo, no concluyente todavía.")
    else:
        print("Sin operaciones en validación.")

    print("=" * 100)


if __name__ == "__main__":
    correr()