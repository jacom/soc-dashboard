#!/usr/bin/env bash
# =============================================================================
# SOC Dashboard — Update Script
# รันโดย do_update view ผ่าน subprocess
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "[update] Pulling latest code from GitHub..."
git pull origin main

echo "[update] Installing dashboard dependencies..."
venv/bin/pip install -r requirements.txt -q

echo "[update] Installing soc-bot dependencies..."
soc-bot/venv/bin/pip install -r soc-bot/requirements.txt -q

echo "[update] Running migrations..."
venv/bin/python manage.py migrate --noinput

echo "[update] Collecting static files..."
venv/bin/python manage.py collectstatic --noinput

echo "[update] Done."
