#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-XRP ETH DOGE SOL}"

PROMPT="Usa directamente las herramientas MCP (crypto-data, crypto-exchange, crypto-technical, crypto-advanced-indicators) para obtener, de estas monedas: $SYMBOLS:
- Precio actual y cambio 24h
- RSI(14) en velas de 1h
- EMA(12) y EMA(26) en velas de 1h, y si hubo un cruce (dorado o de la muerte) en las últimas 2-3 velas
- SMA(200) en velas de 1h, para saber si el precio está por encima o por debajo (tendencia)

NO uses el comando /crypto-trading-desk:quick ni ningún slash command con plantilla fija. NO uses WebSearch ni WebFetch, solo datos MCP en vivo.

REGLA DE ENTRADA (validada por backtesting sobre 360 días, úsala EXACTAMENTE así, sin criterio libre adicional):
- LARGO solo si: precio > SMA200  Y  (RSI < 30  O  hubo cruce dorado de EMA reciente)
- CORTO solo si: precio < SMA200  Y  (RSI > 70  O  hubo cruce de la muerte de EMA reciente)
- Si ninguna moneda cumple la regla, dilo explícitamente: 'Sin señales de entrada válidas en este momento' -- NO inventes una entrada para forzar una señal.

Para cada moneda que SÍ cumpla la regla, incluye: dirección (LARGO/CORTO), precio de entrada, stop-loss (5% en contra), take-profit (3% a favor), y la razón exacta según la regla (ej. 'precio sobre SMA200 + cruce dorado reciente').

Responde ÚNICAMENTE en español. NO incluyas enlaces ni URLs. Formato para Telegram: usa *negrita*, tabla compacta con precio/RSI/tendencia de las 4 monedas primero, luego la sección de señales, sin preámbulo.

Al final, en una línea aparte: 'Basado en backtesting de 360 días, sin comisiones/slippage. No es asesoría financiera.'"

OUTPUT=$(claude -p "$PROMPT" \
  --model claude-haiku-4-5-20251001 \
  --dangerously-skip-permissions \
  --plugin-dir ./crypto-trading-desk)

ESCAPED=$(echo "$OUTPUT" | sed 's/[_*[]/\\&/g')

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d parse_mode="Markdown" \
  -d disable_web_page_preview=true \
  --data-urlencode text="$ESCAPED"