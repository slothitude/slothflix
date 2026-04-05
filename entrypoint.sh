#!/bin/bash
set -e
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    python -u bot.py &
fi
python run.py
