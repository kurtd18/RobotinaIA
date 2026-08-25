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

    # Umbral de score a partir del cual AlertEngine.get_recommendation()
    # devuelve "OPORTUNIDAD" en vez de "REVISAR". Satisface el contrato ya
    # existente en tests/test_alert.py (65 -> REVISAR, 95 -> OPORTUNIDAD),
    # coherente con el umbral >=50 = REVISAR ya definido en alert_engine.py.
    UMBRAL_SENAL = 80

    # Máquina de estados de alertas (app/alerts/alert_state.py, Épica 5).
    # Un stop-loss/target sin resolver se recuerda cada
    # ALERTA_RECORDATORIO_HORAS horas si no hay una novedad de precio, y
    # de inmediato si el precio empeora más de ALERTA_CAMBIO_MATERIAL_PCT
    # respecto al extremo ya registrado - así se evita el bug de "se
    # avisa una sola vez y nunca más" que dejó la posición BTC-USD
    # estancada indefinidamente.
    ALERTA_RECORDATORIO_HORAS = 6
    ALERTA_CAMBIO_MATERIAL_PCT = 0.5

    # Trailing stop (stop loss dinámico): cuando el precio alcanza el
    # objetivo, ese nivel se vuelve el nuevo stop y el objetivo sube
    # este porcentaje más. Vive acá (no en portfolio_alerts.py ni en
    # portfolio_service.py) porque ambos módulos lo necesitan y
    # definirlo en cualquiera de los dos crea un import circular entre
    # ellos - un valor compartido sin dependencias es la forma correcta
    # de evitarlo, no un import perezoso.
    TRAILING_STEP_PCT = 0.03

    # La estrategia RSI(2) Connors revisa cada INTERVALO_REVISION_MINUTOS
    # minutos, solo dentro de la ventana HORA_INICIO_REVISION a
    # HORA_FIN_REVISION (America/Bogota) - fuera de esa ventana no hace
    # nada. Como usa velas diarias, revisar durante el día da la señal
    # con el precio en vivo (todavía no es el cierre confirmado), no
    # después de cerrado el mercado.
    INTERVALO_REVISION_MINUTOS = 30
    HORA_INICIO_REVISION = "08:00"
    HORA_FIN_REVISION = "17:00"

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