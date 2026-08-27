#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-BTC ETH SOL}"

# Corre el análisis rápido en modo headless.
# --dangerously-skip-permissions es necesario porque no hay sesión interactiva
# para aprobar cada herramienta MCP; el pipeline solo usa herramientas de
# solo-lectura (precios, funding rate, fear&greed), no ejecuta trades.
OUTPUT=$(claude -p "Run /crypto-trading-desk:quick for these symbols: $SYMBOLS. Return only the summary, no preamble. If any MCP data tool is unavailable, say so explicitly instead of substituting web search data." \
  --dangerously-skip-permissions \
  --plugin-dir ./crypto-trading-desk)

# Escapa caracteres especiales de Markdown de Telegram
ESCAPED=$(echo "$OUTPUT" | sed 's/[_*[]/\\&/g')

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d parse_mode="Markdown" \
  --data-urlencode text="$ESCAPED"