import sys
sys.path.insert(0, '.')
import yfinance as yf

ACTIVOS = [
    "PFCIBEST.CL", "ECOPETROL.CL", "GEB.CL", "GRUPOARGOS.CL", "CEMARGOS.CL",
    "CELSIA.CL", "GRUPOSURA.CL", "PFDAVVNDA.CL", "TERPEL.CL", "NUTRESA.CL",
]

for symbol in ACTIVOS:
    data = yf.Ticker(symbol).history(start="2018-01-01", interval="1d")
    if data.empty:
        print(f"{symbol}: sin datos")
        continue
    print(f"{symbol:14} datos desde {data.index[0].strftime('%Y-%m-%d')} hasta {data.index[-1].strftime('%Y-%m-%d')} ({len(data)} días)")