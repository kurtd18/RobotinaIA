#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-BTC ETH XRP BNB SOL DOGE ADA TRX LINK AVAX}"

PROMPT="Usa directamente las herramientas MCP (crypto-data, crypto-exchange, crypto-technical, crypto-futures, crypto-advanced-indicators, crypto-market-microstructure) para obtener precio actual, cambio 24h, funding rate y Fear & Greed Index de estas monedas: $SYMBOLS. NO uses el comando /crypto-trading-desk:quick ni ningún slash command con plantilla fija — arma el reporte tú mismo. NO uses WebSearch ni WebFetch, solo datos MCP en vivo; si alguna herramienta falla, dilo brevemente y sigue con las demás.

Para CADA moneda con: movimiento >5% en 24h, funding rate divergente entre exchanges, o RSI extremo (>70 o <30), incluye un punto de entrada sugerido: dirección (LARGO o CORTO), precio de entrada, stop-loss, y take-profit apuntando a mínimo 3% de ganancia potencial. Basado solo en análisis técnico — etiqueta esto como informativo, no asesoría financiera.

Responde ÚNICAMENTE en español, sin plantillas en inglés. NO incluyas enlaces ni URLs. Formato para Telegram: usa *negrita*, tabla compacta, sin preámbulo."

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