"""
Configuración global de RobotinaIA
"""

import os


class Settings:
    APP_NAME = "RobotinaIA"
    VERSION = "0.1.0"
    AUTHOR = "Elkin Ahumada"

    DEBUG = True

    # En tu PC no hace falta configurar nada, usa "robotinaia.db" tal cual.
    # En Railway, se define la variable de entorno DATABASE_PATH apuntando
    # al volumen persistente (ej. /data/robotinaia.db), para que los datos
    # no se pierdan en cada redeploy.
    DATABASE_NAME = os.getenv("DATABASE_PATH", "robotinaia.db")

    # Ya no lo usa el scheduler principal (main.py) - la estrategia RSI(2)
    # Connors corre una vez al día (ver HORA_EJECUCION_DIARIA), no cada N
    # minutos como el scoring intradía anterior. Se deja la constante por
    # si algún otro módulo todavía la referencia.
    SCAN_INTERVAL_MINUTES = 15

    # Hora del día (America/Bogota) en la que corre la estrategia RSI(2)
    # Connors. Se usa el cierre diario más reciente disponible en Yahoo
    # Finance, así que cualquier hora después del cierre de los mercados
    # relevantes (BVC cierra ~13:00-14:00, EE.UU. ~16:00 ET / ~17:00-18:00
    # Bogotá) funciona - 07:00 da margen de sobra y deja la alerta lista
    # antes de que abra la BVC (~09:30).
    HORA_EJECUCION_DIARIA = "07:00"

    UMBRAL_SENAL = 80

    # Acciones listadas en la BVC. Verificado contra Yahoo Finance el 28/07/2026
    # con scripts/watchlist_scanner.py. Quitados de la lista original:
    # - BCOLOMBIA / PFBCOLOM: Bancolombia se renombró a Grupo Cibest, son
    #   el mismo activo que CIBEST / PFCIBEST (que sí están abajo).
    # - AVVILLAS / DAVIVIENDA: Yahoo Finance no tiene datos para estos.
    # - CLH: Cemex Latam Holdings fue deslistada de la BVC en abril 2023.
    ACTIVOS_BVC = [
        "ECOPETROL.CL",
        "BOGOTA.CL",
        "OCCIDENTE.CL",
        "POPULAR.CL",
        "GRUPOAVAL.CL",
        "PFAVAL.CL",
        "CIBEST.CL",
        "PFCIBEST.CL",
        "GRUPOARGOS.CL",
        "PFGRUPOARG.CL",
        "CEMARGOS.CL",
        "PFCEMARGOS.CL",
        "GRUPOSURA.CL",
        "PFGRUPSURA.CL",
        "NUTRESA.CL",
        "EXITO.CL",
        "ISA.CL",
        "GEB.CL",
        "CELSIA.CL",
        "PROMIGAS.CL",
        "MINEROS.CL",
        "BVC.CL",
        "CORFICOLCF.CL",
        "ENKA.CL",
        "ETB.CL",
        "CONCONCRET.CL",
        "FABRICATO.CL",
        "PAZRIO.CL",
        "CNEC.CL",
    ]

    # Acciones internacionales, vía Mercado Global Colombiano (MGC).
    # Verificado contra Yahoo Finance el 28/07/2026.
    ACTIVOS_INTERNACIONAL = [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "TSLA",
        "BRK-B",             # corregido de BRK.B (Yahoo usa guion)
        "JPM",
        "BAC",
        "C",
        "JNJ",
        "PFE",
        "GE",
        "GEHC",
        "UBER",
        "NU",
        "F",
        "NKE",
        "ENEL.MI",           # corregido de ENEL (bolsa de Milán)
        "FALABELLA.SN",      # corregido de FALABELLA (bolsa de Santiago)
        "CENCOSUD.SN",       # corregido de CENCOSUD (bolsa de Santiago)
        "SQM",
        "BCH",
    ]

    # ETF internacionales vía MGC. Verificado contra Yahoo Finance el 28/07/2026.
    # ICHN ("ETF China Large Caps") no se pudo identificar con certeza -
    # pendiente confirmar el ticker real antes de agregarlo.
    ACTIVOS_ETF = [
        "CSPX.L",
        "ISAC.L",
        "IUIT.L",
        "IBIT",
        "IB01.L",
        "GOAU",
        "IWVL.L",
    ]

    ACTIVOS_CRIPTO = [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
    ]

    @classmethod
    def todos_los_activos(cls):
        return (
            cls.ACTIVOS_BVC
            + cls.ACTIVOS_INTERNACIONAL
            + cls.ACTIVOS_ETF
            + cls.ACTIVOS_CRIPTO
        )