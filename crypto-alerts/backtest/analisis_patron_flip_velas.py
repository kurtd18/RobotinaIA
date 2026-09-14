"""
Busca patrones que preceden a un "flip" de color de vela (roja -> verde,
o verde -> roja) que SÍ se convierte en un movimiento real, en velas
DIARIAS de las 7 monedas ya seleccionadas (XRP, ADA, DOGE, LINK, AVAX,
DOT, LTC), 730 días.

Metodología:
  1. Se calculan ~20 indicadores técnicos (RSI, Estocástico, MACD, EMAs,
     SMA200, Bollinger%B, ATR, ADX/DI, CCI, Williams%R, MFI, OBV, ROC,
     CMF, momentum, volumen) + 4 features de forma de vela (tamaño del
     cuerpo, mecha superior, mecha inferior, rango total, todo en % del
     precio de apertura).
  2. Se detectan los "flips": una vela roja seguida de una verde
     (candidato a LARGO) o una verde seguida de una roja (candidato a
     CORTO).
  3. Un flip cuenta como "éxito" solo si en los siguientes
     VENTANA_EXITO_VELAS el precio se mueve al menos GANANCIA_MINIMA_%
     a favor de esa dirección - así se filtra el ruido de un solo día
     verde en medio de una tendencia bajista que sigue cayendo al otro
     día.
  4. Para cada condición candidata (indicador o forma de vela), medida
     en la vela del flip, se calcula precisión = % de las veces que esa
     condición estuvo activa Y el flip fue un éxito real - igual
     metodología que analisis_falsos_positivos_xrp.py, pero ahora sobre
     7 monedas y sobre flips diarios en vez de cruces EMA.

Uso:
    pip install -r requirements.txt
    python analisis_patron_flip_velas.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd

from analisis_puntos_quiebre_xrp import EXCHANGE_ID, fetch_ohlcv_full, calcular_indicadores
from backtest_cron_gaps import SYMBOLS

TIMEFRAME = "1d"
LOOKBACK_DAYS = 730

VENTANA_EXITO_VELAS = 5      # días para confirmar que el flip fue un movimiento real
GANANCIA_MINIMA_PCT = 3.0    # % mínimo a favor para contar como éxito


def agregar_forma_vela(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    df["cuerpo_%"] = (c - o).abs() / o * 100
    df["mecha_sup_%"] = (h - c.where(c >= o, o)) / o * 100
    df["mecha_inf_%"] = (o.where(c >= o, c) - l) / o * 100
    df["rango_total_%"] = (h - l) / o * 100
    df["color"] = np.where(c > o, "verde", np.where(c < o, "roja", "doji"))
    return df


def detectar_flips(df: pd.DataFrame, warmup: int) -> tuple[list, list]:
    """Flips roja->verde (candidatos LARGO) y verde->roja (candidatos
    CORTO). idx apunta a la vela del flip (la que cambió de color)."""
    flips_largo, flips_corto = [], []
    color = df["color"].values

    for i in range(warmup + 1, len(df) - VENTANA_EXITO_VELAS):
        if color[i - 1] == "roja" and color[i] == "verde":
            flips_largo.append(i)
        elif color[i - 1] == "verde" and color[i] == "roja":
            flips_corto.append(i)

    return flips_largo, flips_corto


def marcar_exito(df: pd.DataFrame, idxs: list[int], direccion: str,
                  ganancia_minima_pct: float = GANANCIA_MINIMA_PCT,
                  ventana_velas: int = VENTANA_EXITO_VELAS) -> np.ndarray:
    """True si, dentro de `ventana_velas` después del flip, el precio se
    movió >= `ganancia_minima_pct` a favor de la dirección."""
    close, high, low = df["close"].values, df["high"].values, df["low"].values
    exito = np.zeros(len(idxs), dtype=bool)

    for pos, i in enumerate(idxs):
        entrada = close[i]
        limite = min(i + ventana_velas, len(df) - 1)
        if direccion == "LARGO":
            mejor = high[i + 1:limite + 1].max() if limite > i else entrada
            exito[pos] = (mejor - entrada) / entrada * 100 >= ganancia_minima_pct
        else:
            peor = low[i + 1:limite + 1].min() if limite > i else entrada
            exito[pos] = (entrada - peor) / entrada * 100 >= ganancia_minima_pct

    return exito


CONDICIONES_LARGO = {
    "RSI < 30": lambda df, i: df["rsi14"].iloc[i] < 30,
    "RSI < 45": lambda df, i: df["rsi14"].iloc[i] < 45,
    "MFI < 20": lambda df, i: df["mfi14"].iloc[i] < 20,
    "Estocástico < 20": lambda df, i: df["stoch_k"].iloc[i] < 20,
    "CCI < -100": lambda df, i: df["cci20"].iloc[i] < -100,
    "Williams %R < -80": lambda df, i: df["willr14"].iloc[i] < -80,
    "Bollinger %B < 0": lambda df, i: df["bb_pct_b"].iloc[i] < 0,
    "Precio < SMA200 (bajista)": lambda df, i: df["close"].iloc[i] < df["sma200"].iloc[i] if pd.notna(df["sma200"].iloc[i]) else False,
    "Precio > SMA200 (alcista)": lambda df, i: df["close"].iloc[i] > df["sma200"].iloc[i] if pd.notna(df["sma200"].iloc[i]) else False,
    "DI- > DI+ (venta dominante previa)": lambda df, i: df["dmn"].iloc[i] > df["dmp"].iloc[i],
    "ADX > 25 (tendencia fuerte previa)": lambda df, i: df["adx"].iloc[i] > 25,
    "Volumen > 1.5x promedio (flip con fuerza)": lambda df, i: df["vol_ratio"].iloc[i] > 1.5,
    "Volumen > 2x promedio": lambda df, i: df["vol_ratio"].iloc[i] > 2.0,
    "Mecha inferior > 2x el cuerpo (tipo martillo)": lambda df, i: df["mecha_inf_%"].iloc[i] > 2 * df["cuerpo_%"].iloc[i] if df["cuerpo_%"].iloc[i] > 0 else False,
    "Cuerpo grande (>=3% del precio)": lambda df, i: df["cuerpo_%"].iloc[i] >= 3.0,
    "CMF < 0 (flujo vendedor previo)": lambda df, i: df["cmf20"].iloc[i] < 0,
    "OBV bajando (últimas 20 velas)": lambda df, i: df["obv_slope20"].iloc[i] < 0,
}

CONDICIONES_CORTO = {
    "RSI > 70": lambda df, i: df["rsi14"].iloc[i] > 70,
    "RSI > 55": lambda df, i: df["rsi14"].iloc[i] > 55,
    "MFI > 80": lambda df, i: df["mfi14"].iloc[i] > 80,
    "Estocástico > 80": lambda df, i: df["stoch_k"].iloc[i] > 80,
    "CCI > 100": lambda df, i: df["cci20"].iloc[i] > 100,
    "Williams %R > -20": lambda df, i: df["willr14"].iloc[i] > -20,
    "Bollinger %B > 1": lambda df, i: df["bb_pct_b"].iloc[i] > 1,
    "Precio > SMA200 (alcista)": lambda df, i: df["close"].iloc[i] > df["sma200"].iloc[i] if pd.notna(df["sma200"].iloc[i]) else False,
    "Precio < SMA200 (bajista)": lambda df, i: df["close"].iloc[i] < df["sma200"].iloc[i] if pd.notna(df["sma200"].iloc[i]) else False,
    "DI+ > DI- (compra dominante previa)": lambda df, i: df["dmp"].iloc[i] > df["dmn"].iloc[i],
    "ADX > 25 (tendencia fuerte previa)": lambda df, i: df["adx"].iloc[i] > 25,
    "Volumen > 1.5x promedio (flip con fuerza)": lambda df, i: df["vol_ratio"].iloc[i] > 1.5,
    "Volumen > 2x promedio": lambda df, i: df["vol_ratio"].iloc[i] > 2.0,
    "Mecha superior > 2x el cuerpo (tipo estrella fugaz)": lambda df, i: df["mecha_sup_%"].iloc[i] > 2 * df["cuerpo_%"].iloc[i] if df["cuerpo_%"].iloc[i] > 0 else False,
    "Cuerpo grande (>=3% del precio)": lambda df, i: df["cuerpo_%"].iloc[i] >= 3.0,
    "CMF > 0 (flujo comprador previo)": lambda df, i: df["cmf20"].iloc[i] > 0,
    "OBV subiendo (últimas 20 velas)": lambda df, i: df["obv_slope20"].iloc[i] > 0,
}


def evaluar_condiciones(dfs: dict, flips_por_symbol: dict, exitos_por_symbol: dict, condiciones: dict) -> pd.DataFrame:
    filas = []
    for nombre, fn in condiciones.items():
        total_activadas, total_exitosas = 0, 0
        for symbol, idxs in flips_por_symbol.items():
            df = dfs[symbol]
            exitos = exitos_por_symbol[symbol]
            for pos, i in enumerate(idxs):
                try:
                    activa = fn(df, i)
                except Exception:
                    activa = False
                if activa:
                    total_activadas += 1
                    if exitos[pos]:
                        total_exitosas += 1

        if total_activadas == 0:
            continue
        filas.append({
            "condición": nombre,
            "veces_activada": total_activadas,
            "precisión_%": round(total_exitosas / total_activadas * 100, 1),
        })

    return pd.DataFrame(filas).sort_values("precisión_%", ascending=False)


def main():
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    warmup = 200

    dfs = {}
    flips_largo_por_symbol, flips_corto_por_symbol = {}, {}
    exitos_largo_por_symbol, exitos_corto_por_symbol = {}, {}

    for symbol in SYMBOLS:
        print(f"Procesando {symbol} ...")
        df = fetch_ohlcv_full(exchange, symbol, TIMEFRAME, since_ms)
        df = calcular_indicadores(df)
        df = agregar_forma_vela(df)
        dfs[symbol] = df

        flips_largo, flips_corto = detectar_flips(df, warmup)
        flips_largo_por_symbol[symbol] = flips_largo
        flips_corto_por_symbol[symbol] = flips_corto

        exitos_largo_por_symbol[symbol] = marcar_exito(df, flips_largo, "LARGO")
        exitos_corto_por_symbol[symbol] = marcar_exito(df, flips_corto, "CORTO")

        print(f"  {len(flips_largo)} flips roja->verde ({exitos_largo_por_symbol[symbol].sum()} éxitos), "
              f"{len(flips_corto)} flips verde->roja ({exitos_corto_por_symbol[symbol].sum()} éxitos)")

    total_flips_largo = sum(len(v) for v in flips_largo_por_symbol.values())
    total_exitos_largo = sum(int(e.sum()) for e in exitos_largo_por_symbol.values())
    total_flips_corto = sum(len(v) for v in flips_corto_por_symbol.values())
    total_exitos_corto = sum(int(e.sum()) for e in exitos_corto_por_symbol.values())

    print("\n" + "=" * 90)
    print(f"TASA BASE: de todos los flips roja->verde, {total_exitos_largo}/{total_flips_largo} "
          f"({total_exitos_largo / total_flips_largo * 100:.1f}%) fueron éxito real (>= {GANANCIA_MINIMA_PCT}% "
          f"en <= {VENTANA_EXITO_VELAS} días)")
    print(f"TASA BASE: de todos los flips verde->roja, {total_exitos_corto}/{total_flips_corto} "
          f"({total_exitos_corto / total_flips_corto * 100:.1f}%) fueron éxito real")
    print("=" * 90)

    print("\n" + "=" * 90)
    print("PRECISIÓN DE CONDICIONES EN FLIPS ROJA->VERDE (candidatos a LARGO)")
    print("=" * 90)
    df_largo = evaluar_condiciones(dfs, flips_largo_por_symbol, exitos_largo_por_symbol, CONDICIONES_LARGO)
    print(df_largo.to_string(index=False))
    df_largo.to_csv("resultados_flip_velas_largo.csv", index=False)

    print("\n" + "=" * 90)
    print("PRECISIÓN DE CONDICIONES EN FLIPS VERDE->ROJA (candidatos a CORTO)")
    print("=" * 90)
    df_corto = evaluar_condiciones(dfs, flips_corto_por_symbol, exitos_corto_por_symbol, CONDICIONES_CORTO)
    print(df_corto.to_string(index=False))
    df_corto.to_csv("resultados_flip_velas_corto.csv", index=False)

    # --- Combos para CORTO (las 3 condiciones con mejor precisión y muestra razonable) ---
    combos_corto = {
        "Volumen>2x Y Williams%R>-20": lambda df, i: (df["vol_ratio"].iloc[i] > 2.0) and (df["willr14"].iloc[i] > -20),
        "Estocástico>80 Y Williams%R>-20": lambda df, i: (df["stoch_k"].iloc[i] > 80) and (df["willr14"].iloc[i] > -20),
        "Volumen>1.5x Y Estocástico>80 Y Williams%R>-20": lambda df, i: (
            df["vol_ratio"].iloc[i] > 1.5 and df["stoch_k"].iloc[i] > 80 and df["willr14"].iloc[i] > -20
        ),
    }
    print("\n" + "=" * 90)
    print("COMBOS PARA CORTO")
    print("=" * 90)
    df_combos_corto = evaluar_condiciones(dfs, flips_corto_por_symbol, exitos_corto_por_symbol, combos_corto)
    print(df_combos_corto.to_string(index=False))

    # --- LARGO con criterio más exigente (5% en 3 días en vez de 3% en 5 días) ---
    exitos_largo_estricto = {
        s: marcar_exito(dfs[s], flips_largo_por_symbol[s], "LARGO", ganancia_minima_pct=5.0, ventana_velas=3)
        for s in SYMBOLS
    }
    total_exitos_estricto = sum(int(e.sum()) for e in exitos_largo_estricto.values())
    print("\n" + "=" * 90)
    print(f"LARGO con criterio más estricto (>=5% en <=3 días): base = "
          f"{total_exitos_estricto}/{total_flips_largo} ({total_exitos_estricto / total_flips_largo * 100:.1f}%)")
    print("=" * 90)
    df_largo_estricto = evaluar_condiciones(dfs, flips_largo_por_symbol, exitos_largo_estricto, CONDICIONES_LARGO)
    print(df_largo_estricto.to_string(index=False))
    df_largo_estricto.to_csv("resultados_flip_velas_largo_estricto.csv", index=False)


if __name__ == "__main__":
    main()
