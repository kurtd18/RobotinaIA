#!/usr/bin/env bash
set -euo pipefail

SYMBOLS="${1:-BTC ETH SOL}"

# Corre el análisis rápido en modo headless, con permisos pre-aprobados
OUTPUT=$(claude -p "Run /crypto-trading-desk:quick for these symbols: $SYMBOLS. Return only the summary, no preamble." \
  --allowedTools "mcp__crypto-data,mcp__crypto-exchange,mcp__crypto-technical,mcp__crypto-futures,mcp__crypto-advanced-indicators,mcp__crypto-market-microstructure,mcp__crypto-learning-db,WebSearch,WebFetch" \
  --plugin-dir ./crypto-trading-desk)

# Escapa caracteres especiales de Markdown de Telegram
ESCAPED=$(echo "$OUTPUT" | sed 's/[_*[]/\\&/g')

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d parse_mode="Markdown" \
  --data-urlencode text="$ESCAPED"