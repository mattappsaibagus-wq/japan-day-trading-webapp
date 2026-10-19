#!/usr/bin/env bash
# Runner for Japan Day Trading Terminal
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo "[*] Launching Kabutrader Japan Day Trading Terminal on http://127.0.0.1:${KABU_PORT:-5000}"
exec .venv/bin/python app.py
