#!/usr/bin/env bash
# Runner for Japan Day Trading Terminal
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

PORT=5000
echo "[*] Launching Kabutrader Japan Day Trading Terminal on http://127.0.0.1:${PORT}"
exec python3 app.py
