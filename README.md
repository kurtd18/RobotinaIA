# 🤖 RobotinaIA

Asistente personal de inversión para la Bolsa de Valores de Colombia (BVC), acciones internacionales y criptomonedas. Analiza el mercado con indicadores técnicos, detecta oportunidades, gestiona un portafolio con stop loss dinámico (trailing stop), y todo se opera por Telegram.

---

## Estado del proyecto

**En uso activo.** No es un prototipo: corre 24/7, gestiona un portafolio real (o simulado, según cómo lo uses) y notifica por Telegram. Sigue en desarrollo incremental — el roadmap está en [`docs/BACKLOG.md`](docs/BACKLOG.md).

---

## Qué hace

- **Motor de scoring técnico** — analiza los activos configurados (BVC, internacional, cripto) cada 15 minutos usando RSI, EMA, VWAP, MACD, ATR y volumen. Cuando el score supera el umbral, genera una señal.
- **Notificación de oportunidades por Telegram** — cada señal llega con el score, una recomendación (`NO COMPRAR` / `REVISAR` / `OPORTUNIDAD`), y un stop loss (-1%) y objetivo (+3%) ya calculados.
- **Gestión de portafolio con trailing stop** — al comprar (`/buy`), el sistema vigila la posición: si el precio sube y toca el objetivo, ese nivel se convierte en el nuevo stop loss (dejando correr la ganancia sin vender). Si el precio cae hasta el stop, te avisa y te deja decidir (`/vender` o `/mantener`) — nunca vende sola.
- **Análisis con IA** — `/analisis ACTIVO` genera un análisis (resumen, riesgo, recomendación) usando un modelo local vía Ollama.
- **Dashboard en Streamlit** — panel de control con las señales generadas.
- **Bot de Telegram** como interfaz principal — todo se opera con comandos, sin tocar la base de datos a mano.

---

## Arquitectura
RobotinaIA/
├── main.py # Scheduler: corre el ciclo completo cada 15 min, 24/7
├── scoring.py # Motor de scoring técnico
├── portfolio.py # Gestión de posiciones (alta, cierre, trailing stop)
├── signal_manager.py # Gestión y expiración de señales
├── stats.py # Estadísticas de señales
├── init_db.py # Inicialización / migración de la base de datos
├── telegram_bot.py # Bot de Telegram (registra los comandos)
├── telegram_commands.py # Lógica de cada comando del bot
│
├── app/
│ ├── core/ # Settings centralizado, prototipo de arquitectura
│ ├── database/ # Conexión, esquema y acceso a datos (SQLite)
│ ├── indicators/ # Cálculo de indicadores técnicos reutilizables
│ ├── alerts/ # Alertas de portafolio (trailing stop, stop loss)
│ ├── ai/ # Motor de análisis con IA (Ollama)
│ ├── services/ # Telegram (envío de mensajes) y clasificador de score
│ ├── providers/ # Abstracción de proveedor de datos de mercado (ver ADR-001)
│ ├── models/ # Modelos de dominio
│ └── dashboard/ # Panel de control (Streamlit)
│
├── scripts/ # Herramientas manuales (no corren solas)
│ ├── check_env.py # Verifica que las variables de entorno estén configuradas
│ ├── check_telegram.py # Prueba el envío de un mensaje real
│ ├── check_yfinance.py # Prueba la conexión con Yahoo Finance
│ ├── check_gemini.py # Prueba la conexión con la API de Gemini
│ └── watchlist_scanner.py # Consulta rápida de precios sin pasar por el scoring
│
├── tests/ # Pruebas automatizadas (pytest)
└── docs/ # Visión, arquitectura, decisiones (ADRs) y backlog
---

## Requisitos previos

- Python 3.12
- Un bot de Telegram (crear uno gratis con [@BotFather](https://t.me/BotFather))
- [Ollama](https://ollama.com) corriendo localmente, con el modelo `llama3.1` descargado, si vas a usar `/analisis`

---

## Instalación

```bash
git clone <url-del-repositorio>
cd RobotinaIA

python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell)
# source .venv/bin/activate       # Linux / Mac

pip install -r requirements.txt

copy .env.example .env            # Windows
# cp .env.example .env            # Linux / Mac
```

Completa `.env` con tus valores reales:

| Variable | Requerida | Descripción |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Sí | Token del bot, obtenido de @BotFather |
| `TELEGRAM_CHAT_ID` | Sí | ID del chat donde el bot envía y recibe mensajes |
| `GEMINI_API_KEY` | No | Solo si usas `scripts/check_gemini.py` |

Inicializa la base de datos:

```bash
python init_db.py
```

---

## Cómo correr

**El scheduler** (motor de scoring + trailing stop, corre 24/7):

```bash
python main.py
```

**El bot de Telegram** (en otra terminal, para poder usar los comandos):

```bash
python telegram_bot.py
```

**El dashboard**:

```bash
streamlit run app/dashboard/dashboard.py
```

---

## Comandos de Telegram

| Comando | Descripción |
|---|---|
| `/ping` | Confirma que el bot está activo |
| `/portfolio` | Muestra las posiciones abiertas |
| `/buy SIGNAL_ID CANTIDAD` | Compra a partir de una señal (stop -1% y objetivo +3% automáticos) |
| `/sell ID PRECIO` | Cierra una posición manualmente |
| `/vender ID PRECIO` | Cierra una posición en respuesta a una alerta de stop loss |
| `/mantener ID` | Mantiene la posición pese a la alerta de stop loss |
| `/analisis ACTIVO` | Genera un análisis con IA de un activo monitoreado |

---

## Tests

```bash
python -m pytest tests/ -v
```

---

## Activos monitoreados

Configurados en `app/core/settings.py` (`Settings.ACTIVOS_BVC`, `ACTIVOS_INTERNACIONAL`, `ACTIVOS_CRIPTO`).

---

## Documentación adicional

- [`docs/VISION.md`](docs/VISION.md) — visión y principios del proyecto
- [`docs/Arquitectura.md`](docs/Arquitectura.md) — arquitectura planeada
- [`docs/BACKLOG.md`](docs/BACKLOG.md) — historial de qué se hizo y qué falta
- [`docs/ADR-001-Proveedor-de-Datos.md`](docs/ADR-001-Proveedor-de-Datos.md) — decisión sobre proveedores de datos de mercado

---

## Autor

Elkin Ahumada