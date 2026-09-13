"""
Análisis exploratorio de XRP/USDT (Binance, velas 1h, 730 días): busca los
puntos de quiebre reales de la estructura de precio (reversiones tipo "V"
como en el ejemplo del usuario - fondo/techo seguido de un movimiento
sostenido en la otra dirección) y revisa qué combinación de hasta 20
indicadores técnicos estaba presente justo en esos puntos, tanto para
detectar comienzo de LARGO como de CORTO.

Metodología:
  1. Detecta pivotes de precio con un algoritmo tipo ZigZag: un pivote es
     válido solo si el precio se movió al menos UMBRAL_PIVOTE_PCT desde el
     pivote anterior (filtra el ruido normal de las velas 1h).
  2. De esos pivotes, se queda solo con los que después SÍ generaron una
     ganancia relevante en la dirección esperada (mínimo GANANCIA_MINIMA_PCT
     en las siguientes VENTANA_CONFIRMACION_HORAS) - esos son los "puntos de
     quiebre reales" (equivalentes al ejemplo de la vela verde gigante en
     el mínimo de $1.31-1.33 que sí arrancó una reversión sostenida).
  3. En cada punto de quiebre, calcula el estado de 20 indicadores técnicos
     (RSI, Estocástico, MACD, EMAs 12/26/50, SMA20/200, Bollinger %B, ATR,
     ADX+DI, CCI, Williams %R, MFI, OBV, ROC, ratio de volumen, CMF,
     momentum, volatilidad de retornos) y los clasifica en condiciones
     binarias legibles (ej. "RSI < 30", "cruce dorado EMA12/26 reciente").
  4. Agrega qué % de los puntos de quiebre de LARGO (y de CORTO) tenían
     cada condición activa, para encontrar la combinación más frecuente.

Uso:
    pip install -r requirements.txt
    python analisis_puntos_quiebre_xrp.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd

SYMBOL = "XRP/USDT"
EXCHANGE_ID = "binance"
TIMEFRAME = "1h"
LOOKBACK_DAYS = 730

UMBRAL_PIVOTE_PCT = 4.0          # % mínimo de movimiento para marcar un pivote (filtra ruido)
GANANCIA_MINIMA_PCT = 5.0        # % mínimo de movimiento a favor tras el pivote para contarlo como "quiebre real"
VENTANA_CONFIRMACION_HORAS = 72  # tiempo máximo para alcanzar esa ganancia


def fetch_ohlcv_full(exchange, symbol, timeframe, since_ms):
    all_rows = []
    since = since_ms
    limit = 1000
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + 1
        if len(batch) < limit:
            break
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _wilder_smooth(serie: pd.Series, length: int) -> pd.Series:
    return serie.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    df["rsi14"] = _rsi(close, 14)

    # Estocástico %K/%D (14, 3, 3)
    low14, high14 = low.rolling(14).min(), high.rolling(14).max()
    stoch_k_crudo = (close - low14) / (high14 - low14) * 100
    df["stoch_k"] = stoch_k_crudo.rolling(3).mean()
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    # MACD (12, 26, 9)
    ema12, ema26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    df["ema12"] = ema12
    df["ema26"] = ema26
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["sma20"] = close.rolling(20).mean()
    df["sma200"] = close.rolling(200).mean()

    # Bollinger Bands (20, 2)
    sma20, std20 = close.rolling(20).mean(), close.rolling(20).std()
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_pct_b"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

    # ATR (14, suavizado de Wilder)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr14"] = _wilder_smooth(tr, 14)
    df["atr_pct"] = df["atr14"] / close * 100

    # ADX + DI+/DI- (14, suavizado de Wilder)
    up_move, down_move = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    atr_para_di = _wilder_smooth(tr, 14)
    df["dmp"] = 100 * _wilder_smooth(plus_dm, 14) / atr_para_di
    df["dmn"] = 100 * _wilder_smooth(minus_dm, 14) / atr_para_di
    dx = (df["dmp"] - df["dmn"]).abs() / (df["dmp"] + df["dmn"]) * 100
    df["adx"] = _wilder_smooth(dx, 14)

    # CCI (20)
    precio_tipico = (high + low + close) / 3
    sma_tipico = precio_tipico.rolling(20).mean()
    desviacion_media = precio_tipico.rolling(20).apply(lambda x: (x - x.mean()).abs().mean(), raw=False)
    df["cci20"] = (precio_tipico - sma_tipico) / (0.015 * desviacion_media)

    # Williams %R (14)
    df["willr14"] = (high14 - close) / (high14 - low14) * -100

    # MFI (14)
    flujo_dinero = precio_tipico * volume
    direccion = precio_tipico.diff()
    flujo_positivo = flujo_dinero.where(direccion > 0, 0.0).rolling(14).sum()
    flujo_negativo = flujo_dinero.where(direccion < 0, 0.0).rolling(14).sum()
    ratio_flujo = flujo_positivo / flujo_negativo
    df["mfi14"] = 100 - (100 / (1 + ratio_flujo))

    # OBV
    signo = np.sign(close.diff().fillna(0))
    df["obv"] = (signo * volume).cumsum()
    df["obv_slope20"] = df["obv"].diff(20)

    # ROC (10) y momentum (10)
    df["roc10"] = close.pct_change(10) * 100
    df["mom10"] = close.diff(10)

    # CMF (20)
    mfm = ((close - low) - (high - close)) / (high - low)
    mfv = mfm * volume
    df["cmf20"] = mfv.rolling(20).sum() / volume.rolling(20).sum()

    df["vol_sma20"] = volume.rolling(20).mean()
    df["vol_ratio"] = volume / df["vol_sma20"]

    df["retorno_1h"] = close.pct_change()
    df["volatilidad20"] = df["retorno_1h"].rolling(20).std() * 100

    diff_ema = df["ema12"] - df["ema26"]
    prev_diff = diff_ema.shift(1)
    df["cruce_ema"] = None
    df.loc[(prev_diff < 0) & (diff_ema > 0), "cruce_ema"] = "dorado"
    df.loc[(prev_diff > 0) & (diff_ema < 0), "cruce_ema"] = "muerte"

    return df


def detectar_pivotes(df: pd.DataFrame) -> list[dict]:
    """ZigZag simple: recorre el precio y marca un pivote cada vez que hay
    un giro de al menos UMBRAL_PIVOTE_PCT desde el último pivote."""
    pivotes = []
    precio = df["close"].values
    ts = df.index

    idx_ultimo_pivote = 0
    direccion = None  # "arriba" o "abajo" (hacia dónde se venía moviendo)
    idx_extremo = 0

    for i in range(1, len(precio)):
        cambio_desde_extremo = (precio[i] - precio[idx_extremo]) / precio[idx_extremo] * 100

        if direccion is None:
            if abs(cambio_desde_extremo) >= UMBRAL_PIVOTE_PCT:
                direccion = "arriba" if cambio_desde_extremo > 0 else "abajo"
                pivotes.append({"idx": idx_extremo, "ts": ts[idx_extremo], "precio": precio[idx_extremo],
                                 "tipo": "minimo" if direccion == "arriba" else "maximo"})
                idx_extremo = i
            continue

        if direccion == "arriba":
            if precio[i] > precio[idx_extremo]:
                idx_extremo = i
            elif (precio[idx_extremo] - precio[i]) / precio[idx_extremo] * 100 >= UMBRAL_PIVOTE_PCT:
                pivotes.append({"idx": idx_extremo, "ts": ts[idx_extremo], "precio": precio[idx_extremo], "tipo": "maximo"})
                direccion = "abajo"
                idx_extremo = i
        else:
            if precio[i] < precio[idx_extremo]:
                idx_extremo = i
            elif (precio[i] - precio[idx_extremo]) / precio[idx_extremo] * 100 >= UMBRAL_PIVOTE_PCT:
                pivotes.append({"idx": idx_extremo, "ts": ts[idx_extremo], "precio": precio[idx_extremo], "tipo": "minimo"})
                direccion = "arriba"
                idx_extremo = i

    return pivotes


def filtrar_quiebres_reales(df: pd.DataFrame, pivotes: list[dict]) -> list[dict]:
    """De todos los pivotes, se queda solo con los que de verdad arrancaron
    un movimiento rentable (>= GANANCIA_MINIMA_PCT) dentro de la ventana de
    confirmación - equivalente a "la vela verde gigante que sí revirtió",
    filtrando pivotes que fueron solo ruido o rebotes débiles.
    """
    quiebres = []
    precio = df["close"].values
    ts = df.index

    for p in pivotes:
        i = p["idx"]
        limite = min(i + VENTANA_CONFIRMACION_HORAS, len(precio) - 1)
        ventana = precio[i:limite + 1]
        if len(ventana) < 2:
            continue

        if p["tipo"] == "minimo":
            max_ventana = ventana.max()
            ganancia = (max_ventana - precio[i]) / precio[i] * 100
            if ganancia >= GANANCIA_MINIMA_PCT:
                quiebres.append({**p, "direccion": "LARGO", "ganancia_%_lograda": round(ganancia, 1)})
        else:
            min_ventana = ventana.min()
            ganancia = (precio[i] - min_ventana) / precio[i] * 100
            if ganancia >= GANANCIA_MINIMA_PCT:
                quiebres.append({**p, "direccion": "CORTO", "ganancia_%_lograda": round(ganancia, 1)})

    return quiebres


def condiciones_en_punto(df: pd.DataFrame, idx: int) -> dict:
    """Evalúa hasta 20 condiciones binarias/categóricas de indicadores en
    la vela `idx`, para caracterizar el estado técnico en ese punto."""
    row = df.iloc[idx]

    return {
        "RSI<30 (sobreventa)": row["rsi14"] < 30,
        "RSI>70 (sobrecompra)": row["rsi14"] > 70,
        "Estocástico<20": row["stoch_k"] < 20,
        "Estocástico>80": row["stoch_k"] > 80,
        "MACD hist. positivo": row["macd_hist"] > 0,
        "MACD hist. negativo": row["macd_hist"] < 0,
        "MACD cruzando señal (últimas 3 velas)": bool(
            (df["macd"].iloc[max(0, idx - 3):idx + 1] > df["macd_signal"].iloc[max(0, idx - 3):idx + 1]).diff().abs().sum() > 0
        ),
        "Cruce EMA12/26 dorado (últimas 6 velas)": (df["cruce_ema"].iloc[max(0, idx - 6):idx + 1] == "dorado").any(),
        "Cruce EMA12/26 muerte (últimas 6 velas)": (df["cruce_ema"].iloc[max(0, idx - 6):idx + 1] == "muerte").any(),
        "Precio > EMA50": row["close"] > row["ema50"],
        "Precio < EMA50": row["close"] < row["ema50"],
        "Precio > SMA200 (tendencia alcista)": row["close"] > row["sma200"] if pd.notna(row["sma200"]) else None,
        "Precio < SMA200 (tendencia bajista)": row["close"] < row["sma200"] if pd.notna(row["sma200"]) else None,
        "Bollinger %B < 0 (fuera banda inferior)": row["bb_pct_b"] < 0,
        "Bollinger %B > 1 (fuera banda superior)": row["bb_pct_b"] > 1,
        "ADX > 25 (tendencia fuerte)": row["adx"] > 25,
        "DI+ > DI- (presión compradora)": row["dmp"] > row["dmn"],
        "DI- > DI+ (presión vendedora)": row["dmn"] > row["dmp"],
        "CCI < -100 (sobreventa)": row["cci20"] < -100,
        "CCI > 100 (sobrecompra)": row["cci20"] > 100,
        "Williams %R < -80 (sobreventa)": row["willr14"] < -80,
        "Williams %R > -20 (sobrecompra)": row["willr14"] > -20,
        "MFI < 20 (dinero saliendo, sobreventa)": row["mfi14"] < 20,
        "MFI > 80 (dinero entrando, sobrecompra)": row["mfi14"] > 80,
        "Volumen > 1.5x su promedio 20 velas": row["vol_ratio"] > 1.5,
        "Volumen > 2x su promedio 20 velas": row["vol_ratio"] > 2.0,
        "CMF > 0 (flujo comprador)": row["cmf20"] > 0,
        "CMF < 0 (flujo vendedor)": row["cmf20"] < 0,
        "OBV subiendo (últimas 20 velas)": row["obv_slope20"] > 0,
        "OBV bajando (últimas 20 velas)": row["obv_slope20"] < 0,
        "Volatilidad 20 velas elevada (top 25% histórico)": row["volatilidad20"] > df["volatilidad20"].quantile(0.75),
    }


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    print(f"Descargando {SYMBOL} {TIMEFRAME}, {LOOKBACK_DAYS} días...")
    df = fetch_ohlcv_full(exchange, SYMBOL, TIMEFRAME, since_ms)
    print(f"{len(df)} velas descargadas ({df.index[0]} -> {df.index[-1]})")

    df = calcular_indicadores(df)

    pivotes = detectar_pivotes(df)
    print(f"\n{len(pivotes)} pivotes de precio detectados (umbral {UMBRAL_PIVOTE_PCT}%)")

    quiebres = filtrar_quiebres_reales(df, pivotes)
    largos = [q for q in quiebres if q["direccion"] == "LARGO"]
    cortos = [q for q in quiebres if q["direccion"] == "CORTO"]
    print(f"{len(quiebres)} puntos de quiebre reales confirmados "
          f"(ganancia >= {GANANCIA_MINIMA_PCT}% en <= {VENTANA_CONFIRMACION_HORAS}h): "
          f"{len(largos)} de LARGO, {len(cortos)} de CORTO")

    print("\n" + "=" * 90)
    print("MUESTRA DE PUNTOS DE QUIEBRE DETECTADOS")
    print("=" * 90)
    df_quiebres = pd.DataFrame(quiebres)[["ts", "precio", "direccion", "ganancia_%_lograda"]]
    print(df_quiebres.to_string(index=False))
    df_quiebres.to_csv("resultados_puntos_quiebre_xrp.csv", index=False)

    for etiqueta, lista in [("LARGO", largos), ("CORTO", cortos)]:
        if not lista:
            continue
        print("\n" + "=" * 90)
        print(f"CONDICIONES DE INDICADORES EN LOS {len(lista)} PUNTOS DE QUIEBRE DE {etiqueta}")
        print("(% de las veces que esa condición estaba activa justo en el punto de quiebre)")
        print("=" * 90)

        conteo = {}
        for q in lista:
            cond = condiciones_en_punto(df, q["idx"])
            for nombre, activa in cond.items():
                if activa is None:
                    continue
                conteo.setdefault(nombre, [0, 0])
                conteo[nombre][1] += 1
                if activa:
                    conteo[nombre][0] += 1

        filas = []
        for nombre, (si, total) in conteo.items():
            filas.append({"condición": nombre, "frecuencia_%": round(si / total * 100, 1), "n": total})
        df_cond = pd.DataFrame(filas).sort_values("frecuencia_%", ascending=False)
        print(df_cond.to_string(index=False))
        df_cond.to_csv(f"resultados_condiciones_quiebre_{etiqueta.lower()}_xrp.csv", index=False)


if __name__ == "__main__":
    main()
