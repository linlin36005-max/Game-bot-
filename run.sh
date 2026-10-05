#!/bin/sh
set -a
[ -f .env ] && . ./.env
set +a
python3 bot.py
