"""
Análisis estadístico de velas japonesas (candlesticks) para un par de
Binance, con conteo exacto de velas verdes/rojas, cruces de SMA20/SMA50,
y ciclos de sobreventa/sobrecompra de RSI(14).

Todos los números salen de cálculos reales sobre datos descargados de
la API pública de Binance (/api/v3/klines) - nada se estima ni se
redondea a ojo. Si algún dato no está disponible (ej. histórico
insuficiente para una media móvil), se reporta explícitamente como tal.

Parametrizable para volver a correrlo con otro símbolo/timeframe/rango:
    python analisis_velas_doge.py [SYMBOL] [TIMEFRAME] [DESDE] [HASTA]

Ejemplos:
    python analisis_velas_doge.py
    python analisis_velas_doge.py DOGEUSDT 1d 2026-01-01 2026-09-13
    python analisis_velas_doge.py BTCUSDT 4h 2025-01-01 2026-09-13

Uso:
    pip install -r requirements.txt matplotlib
    python analisis_velas_doge.py
"""

import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # sin display - guarda directo a archivo
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

SMA_CORTA, SMA_LARGA = 20, 50
RSI_PERIODO = 14
RSI_SOBREVENTA, RSI_SOBRECOMPRA = 30, 70
UMBRAL_VELA_FUERTE_PCT = 2.0


def parsear_argumentos() -> dict:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "DOGEUSDT"
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "1d"
    desde = sys.argv[3] if len(sys.argv) > 3 else "2026-01-01"
    hasta = sys.argv[4] if len(sys.argv) > 4 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"symbol": symbol, "timeframe": timeframe, "desde": desde, "hasta": hasta}


def descargar_klines(symbol: str, interval: str, desde: str, hasta: str) -> pd.DataFrame:
    """Descarga OHLCV de Binance Spot (endpoint público, sin autenticación),
    paginando de a 1000 velas hasta cubrir todo el rango [desde, hasta]."""
    start_ms = int(datetime.strptime(desde, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.strptime(hasta, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59, second=59).timestamp() * 1000)

    filas = []
    cursor = start_ms
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000}
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        filas.extend(lote)
        cursor = lote[-1][0] + 1
        if len(lote) < 1000:
            break

    if not filas:
        raise RuntimeError(f"Binance no devolvió velas para {symbol} {interval} entre {desde} y {hasta}")

    df = pd.DataFrame(filas, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["fecha"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df[["fecha", "open", "high", "low", "close", "volume"]].set_index("fecha")


def calcular_rsi(close: pd.Series, periodo: int) -> pd.Series:
    delta = close.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    avg_ganancia = ganancia.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    avg_perdida = perdida.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    rs = avg_ganancia / avg_perdida
    return 100 - (100 / (1 + rs))


def clasificar_velas(df: pd.DataFrame) -> pd.DataFrame:
    df["variacion_%"] = (df["close"] - df["open"]) / df["open"] * 100
    df["color"] = df["variacion_%"].apply(lambda v: "verde" if v > 0 else ("roja" if v < 0 else "doji"))
    return df


def conteo_velas(df: pd.DataFrame) -> dict:
    verdes = df[df["color"] == "verde"]
    rojas = df[df["color"] == "roja"]
    dojis = df[df["color"] == "doji"]

    verdes_fuertes = verdes[verdes["variacion_%"] >= UMBRAL_VELA_FUERTE_PCT]
    rojas_fuertes = rojas[rojas["variacion_%"] <= -UMBRAL_VELA_FUERTE_PCT]

    idx_mas_alcista = df["variacion_%"].idxmax()
    idx_mas_bajista = df["variacion_%"].idxmin()

    return {
        "total_velas": len(df),
        "total_verdes": len(verdes),
        "total_rojas": len(rojas),
        "total_dojis": len(dojis),
        "verdes_variacion_%_ge_2": len(verdes_fuertes),
        "rojas_variacion_%_le_neg2": len(rojas_fuertes),
        "promedio_variacion_%_verdes": round(verdes["variacion_%"].mean(), 4) if len(verdes) else None,
        "promedio_variacion_%_rojas": round(rojas["variacion_%"].mean(), 4) if len(rojas) else None,
        "vela_mas_alcista_fecha": idx_mas_alcista,
        "vela_mas_alcista_%": round(df.loc[idx_mas_alcista, "variacion_%"], 4),
        "vela_mas_bajista_fecha": idx_mas_bajista,
        "vela_mas_bajista_%": round(df.loc[idx_mas_bajista, "variacion_%"], 4),
    }


def detectar_cruces_sma(df: pd.DataFrame) -> tuple[list, list]:
    """Cruces de precio (close) contra la SMA corta, viniendo de abajo
    (largo) o de arriba (corto)."""
    close, sma = df["close"], df["sma_corta"]
    cruces_largo, cruces_corto = [], []

    for i in range(1, len(df)):
        if pd.isna(sma.iloc[i - 1]) or pd.isna(sma.iloc[i]):
            continue
        estaba_abajo = close.iloc[i - 1] < sma.iloc[i - 1]
        esta_arriba = close.iloc[i] > sma.iloc[i]
        estaba_arriba = close.iloc[i - 1] > sma.iloc[i - 1]
        esta_abajo = close.iloc[i] < sma.iloc[i]

        if estaba_abajo and esta_arriba:
            cruces_largo.append({"fecha": df.index[i], "precio": close.iloc[i], "sma_corta": sma.iloc[i]})
        elif estaba_arriba and esta_abajo:
            cruces_corto.append({"fecha": df.index[i], "precio": close.iloc[i], "sma_corta": sma.iloc[i]})

    return cruces_largo, cruces_corto


def detectar_ciclos_rsi(df: pd.DataFrame) -> tuple[list, list]:
    """Ciclos completos: RSI entra en sobreventa/sobrecompra y luego
    vuelve a cruzar el umbral en dirección contraria (no solo tocarlo)."""
    rsi = df["rsi"]
    salidas_sobreventa, salidas_sobrecompra = [], []
    en_sobreventa, en_sobrecompra = False, False
    fecha_entrada_sobreventa, fecha_entrada_sobrecompra = None, None

    for i in range(len(df)):
        if pd.isna(rsi.iloc[i]):
            continue

        if rsi.iloc[i] < RSI_SOBREVENTA:
            en_sobreventa = True
            fecha_entrada_sobreventa = df.index[i]
        elif en_sobreventa and rsi.iloc[i] >= RSI_SOBREVENTA:
            salidas_sobreventa.append({
                "fecha_entrada_sobreventa": fecha_entrada_sobreventa,
                "fecha_salida": df.index[i],
                "rsi_salida": round(rsi.iloc[i], 2),
            })
            en_sobreventa = False

        if rsi.iloc[i] > RSI_SOBRECOMPRA:
            en_sobrecompra = True
            fecha_entrada_sobrecompra = df.index[i]
        elif en_sobrecompra and rsi.iloc[i] <= RSI_SOBRECOMPRA:
            salidas_sobrecompra.append({
                "fecha_entrada_sobrecompra": fecha_entrada_sobrecompra,
                "fecha_salida": df.index[i],
                "rsi_salida": round(rsi.iloc[i], 2),
            })
            en_sobrecompra = False

    return salidas_sobreventa, salidas_sobrecompra


def graficar(df: pd.DataFrame, cruces_largo: list, cruces_corto: list, symbol: str, timeframe: str, archivo: str):
    fig, (ax_precio, ax_rsi) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    ax_precio.plot(df.index, df["close"], label="Close", color="#2962ff", linewidth=1.2)
    ax_precio.plot(df.index, df["sma_corta"], label=f"SMA{SMA_CORTA}", color="#ff9800", linewidth=1)
    ax_precio.plot(df.index, df["sma_larga"], label=f"SMA{SMA_LARGA}", color="#9c27b0", linewidth=1)

    if cruces_largo:
        xs = [c["fecha"] for c in cruces_largo]
        ys = [c["precio"] for c in cruces_largo]
        ax_precio.scatter(xs, ys, marker="^", color="green", s=90, zorder=5, label="Cruce LARGO (sobre SMA20)")

    if cruces_corto:
        xs = [c["fecha"] for c in cruces_corto]
        ys = [c["precio"] for c in cruces_corto]
        ax_precio.scatter(xs, ys, marker="v", color="red", s=90, zorder=5, label="Cruce CORTO (bajo SMA20)")

    ax_precio.set_title(f"{symbol} {timeframe} - Precio, SMA{SMA_CORTA}/{SMA_LARGA} y cruces detectados")
    ax_precio.set_ylabel("Precio (USDT)")
    ax_precio.legend(loc="upper left", fontsize=8)
    ax_precio.grid(alpha=0.3)

    ax_rsi.plot(df.index, df["rsi"], color="#00838f", linewidth=1, label=f"RSI({RSI_PERIODO})")
    ax_rsi.axhline(RSI_SOBRECOMPRA, color="red", linestyle="--", linewidth=0.8)
    ax_rsi.axhline(RSI_SOBREVENTA, color="green", linestyle="--", linewidth=0.8)
    ax_rsi.set_ylabel("RSI")
    ax_rsi.set_ylim(0, 100)
    ax_rsi.grid(alpha=0.3)

    ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(archivo, dpi=150)
    print(f"\nGráfico guardado en: {archivo}")


def main():
    args = parsear_argumentos()
    print(f"Descargando {args['symbol']} {args['timeframe']} de {args['desde']} a {args['hasta']}...")

    df = descargar_klines(args["symbol"], args["timeframe"], args["desde"], args["hasta"])
    print(f"{len(df)} velas descargadas ({df.index[0].date()} -> {df.index[-1].date()})")

    nombre_csv = f"velas_{args['symbol']}_{args['timeframe']}_{args['desde']}_a_{args['hasta']}.csv"
    df.to_csv(nombre_csv)
    print(f"CSV guardado en: {nombre_csv}")

    df = clasificar_velas(df)
    df["sma_corta"] = df["close"].rolling(SMA_CORTA).mean()
    df["sma_larga"] = df["close"].rolling(SMA_LARGA).mean()
    df["rsi"] = calcular_rsi(df["close"], RSI_PERIODO)

    stats = conteo_velas(df)

    print("\n" + "=" * 70)
    print("TAREA 2 - CONTEO DE VELAS")
    print("=" * 70)
    print(f"Total de velas:                          {stats['total_velas']}")
    print(f"Velas verdes:                             {stats['total_verdes']}")
    print(f"Velas rojas:                               {stats['total_rojas']}")
    print(f"Velas doji (open == close exacto):         {stats['total_dojis']}")
    print(f"Velas verdes con variación >= +{UMBRAL_VELA_FUERTE_PCT}%:      {stats['verdes_variacion_%_ge_2']}")
    print(f"Velas rojas con variación <= -{UMBRAL_VELA_FUERTE_PCT}%:      {stats['rojas_variacion_%_le_neg2']}")
    if stats["promedio_variacion_%_verdes"] is not None:
        print(f"Promedio variación % (verdes):            {stats['promedio_variacion_%_verdes']:+.4f}%")
    if stats["promedio_variacion_%_rojas"] is not None:
        print(f"Promedio variación % (rojas):              {stats['promedio_variacion_%_rojas']:+.4f}%")
    print(f"Vela más alcista: {stats['vela_mas_alcista_fecha'].date()} ({stats['vela_mas_alcista_%']:+.4f}%)")
    print(f"Vela más bajista: {stats['vela_mas_bajista_fecha'].date()} ({stats['vela_mas_bajista_%']:+.4f}%)")

    velas_disponibles_sma_larga = df["sma_larga"].notna().sum()
    if velas_disponibles_sma_larga == 0:
        print(f"\nAVISO: no hay suficientes velas para calcular SMA{SMA_LARGA} "
              f"(se necesitan {SMA_LARGA}, hay {len(df)}) - esa serie queda vacía, no se aproxima.")

    cruces_largo, cruces_corto = detectar_cruces_sma(df)
    salidas_sobreventa, salidas_sobrecompra = detectar_ciclos_rsi(df)

    print("\n" + "=" * 70)
    print(f"TAREA 3 - CRUCES DE PRECIO CONTRA SMA{SMA_CORTA}")
    print("=" * 70)
    print(f"\nCruces LARGO (precio cruza de abajo hacia arriba de la SMA{SMA_CORTA}): {len(cruces_largo)}")
    for c in cruces_largo:
        print(f"  {c['fecha'].date()}  precio={c['precio']:.6f}  SMA{SMA_CORTA}={c['sma_corta']:.6f}")

    print(f"\nCruces CORTO (precio cruza de arriba hacia abajo de la SMA{SMA_CORTA}): {len(cruces_corto)}")
    for c in cruces_corto:
        print(f"  {c['fecha'].date()}  precio={c['precio']:.6f}  SMA{SMA_CORTA}={c['sma_corta']:.6f}")

    print(f"\nCiclos RSI: entró en sobreventa (<{RSI_SOBREVENTA}) y volvió a subir por encima de {RSI_SOBREVENTA}: "
          f"{len(salidas_sobreventa)}")
    for s in salidas_sobreventa:
        print(f"  entrada={s['fecha_entrada_sobreventa'].date()}  salida={s['fecha_salida'].date()}  "
              f"RSI al salir={s['rsi_salida']}")

    print(f"\nCiclos RSI: entró en sobrecompra (>{RSI_SOBRECOMPRA}) y volvió a bajar por debajo de {RSI_SOBRECOMPRA}: "
          f"{len(salidas_sobrecompra)}")
    for s in salidas_sobrecompra:
        print(f"  entrada={s['fecha_entrada_sobrecompra'].date()}  salida={s['fecha_salida'].date()}  "
              f"RSI al salir={s['rsi_salida']}")

    nombre_grafico = f"grafico_{args['symbol']}_{args['timeframe']}.png"
    graficar(df, cruces_largo, cruces_corto, args["symbol"], args["timeframe"], nombre_grafico)

    resumen_path = f"resumen_velas_{args['symbol']}_{args['timeframe']}.csv"
    pd.DataFrame([stats]).to_csv(resumen_path, index=False)
    print(f"Resumen guardado en: {resumen_path}")


if __name__ == "__main__":
    main()
