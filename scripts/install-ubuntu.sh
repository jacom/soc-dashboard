#!/usr/bin/env bash
# =============================================================================
# SOC Dashboard — Ubuntu 22.04 / 24.04 Installation Script
# รันด้วย: sudo bash install-ubuntu.sh
# =============================================================================
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step() { echo -e "\n${BLUE}══════════════════════════════════════════════${NC}"; \
         echo -e "${BLUE}  $*${NC}"; \
         echo -e "${BLUE}══════════════════════════════════════════════${NC}"; }

# ── Pre-flight ─────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && err "กรุณารันด้วย sudo: sudo bash $0"

# ── Detect source directory (where script lives) ───────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_SRC="$(dirname "$SCRIPT_DIR")"   # parent of scripts/

# ── Prompt for config ──────────────────────────────────────────────────────────
echo -e "\n${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║      SOC Dashboard — Ubuntu Installer        ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}\n"

read -rp "App user (default: soc): " APP_USER
APP_USER="${APP_USER:-soc}"

read -rp "Install path (default: /home/${APP_USER}/soc-dashboard): " APP_DIR
APP_DIR="${APP_DIR:-/home/${APP_USER}/soc-dashboard}"

# Auto-detect server IP
DEFAULT_IP=$(hostname -I | awk '{print $1}')
read -rp "Server IP (default: ${DEFAULT_IP}): " SERVER_IP
SERVER_IP="${SERVER_IP:-$DEFAULT_IP}"

read -rp "Dashboard port (default: 8500): " DASHBOARD_PORT
DASHBOARD_PORT="${DASHBOARD_PORT:-8500}"

read -rp "Gunicorn port (default: 8002): " GUNICORN_PORT
GUNICORN_PORT="${GUNICORN_PORT:-8002}"

read -rp "DB name (default: soc_db): " DB_NAME
DB_NAME="${DB_NAME:-soc_db}"

read -rp "DB user (default: soc_user): " DB_USER
DB_USER="${DB_USER:-soc_user}"

read -rp "DB password (leave blank to auto-generate): " DB_PASS
if [[ -z "$DB_PASS" ]]; then
    DB_PASS=$(openssl rand -hex 16)
    info "Generated DB password: ${DB_PASS}"
fi

SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(50))" 2>/dev/null || openssl rand -hex 50)

read -rp "Install Ollama for AI analysis? [y/N]: " INSTALL_OLLAMA
INSTALL_OLLAMA="${INSTALL_OLLAMA:-n}"

echo ""
info "Configuration summary:"
echo "  App user    : ${APP_USER}"
echo "  Install dir : ${APP_DIR}"
echo "  Server IP   : ${SERVER_IP}"
echo "  Port        : ${DASHBOARD_PORT}"
echo "  DB          : ${DB_NAME} / ${DB_USER}"
echo ""
read -rp "Proceed with installation? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" != "y" ]] && echo "Aborted." && exit 0

# ─────────────────────────────────────────────────────────────────────────────
step "1. System packages"
# ─────────────────────────────────────────────────────────────────────────────
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q \
    python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib \
    redis-server \
    nginx \
    git build-essential libpq-dev \
    curl openssl
ok "System packages installed"

# ─────────────────────────────────────────────────────────────────────────────
step "2. PostgreSQL"
# ─────────────────────────────────────────────────────────────────────────────
systemctl enable --now postgresql

# Create DB user and database (idempotent)
sudo -u postgres psql -v ON_ERROR_STOP=0 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
  ELSE
    ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')
\gexec

GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

ok "PostgreSQL: database '${DB_NAME}' and user '${DB_USER}' ready"

# ─────────────────────────────────────────────────────────────────────────────
step "3. Redis"
# ─────────────────────────────────────────────────────────────────────────────
systemctl enable --now redis-server
redis-cli ping | grep -q PONG && ok "Redis is running" || warn "Redis ping failed"

# ─────────────────────────────────────────────────────────────────────────────
step "4. Create app user and directory"
# ─────────────────────────────────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$APP_USER"
    ok "Created user: ${APP_USER}"
else
    ok "User ${APP_USER} already exists"
fi

mkdir -p "$APP_DIR"
chown "${APP_USER}:${APP_USER}" "$APP_DIR"

# Copy project files if not already there
if [[ "$PROJECT_SRC" != "$APP_DIR" && -f "$PROJECT_SRC/manage.py" ]]; then
    info "Copying project files from ${PROJECT_SRC} → ${APP_DIR}"
    rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
          --exclude='.env' --exclude='staticfiles' \
          "${PROJECT_SRC}/" "${APP_DIR}/"
    chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"
    ok "Project files copied"
elif [[ -f "$APP_DIR/manage.py" ]]; then
    ok "Project files already at ${APP_DIR}"
else
    err "ไม่พบ manage.py ที่ ${APP_DIR} — กรุณา copy project files ก่อน"
fi

# ─────────────────────────────────────────────────────────────────────────────
step "5. Python virtualenv & dependencies"
# ─────────────────────────────────────────────────────────────────────────────
sudo -u "$APP_USER" bash -c "
    cd '${APP_DIR}'
    python3.11 -m venv venv
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r requirements.txt -q
"
ok "Python dependencies installed"

# ─────────────────────────────────────────────────────────────────────────────
step "6. Create .env file"
# ─────────────────────────────────────────────────────────────────────────────
ENV_FILE="${APP_DIR}/.env"

if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists — creating .env.new (ไม่ทับของเดิม)"
    ENV_FILE="${APP_DIR}/.env.new"
fi

cat > "$ENV_FILE" <<EOF
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${SERVER_IP},localhost,127.0.0.1

CSRF_TRUSTED_ORIGINS=http://${SERVER_IP}:${DASHBOARD_PORT}

DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}

REDIS_URL=redis://127.0.0.1:6379/1

DJANGO_DASHBOARD_URL=http://${SERVER_IP}:${DASHBOARD_PORT}

# กรอก token หลัง createsuperuser
SOC_BOT_API_TOKEN=
EOF

chown "${APP_USER}:${APP_USER}" "$ENV_FILE"
chmod 640 "$ENV_FILE"
ok ".env created at ${ENV_FILE}"

# ─────────────────────────────────────────────────────────────────────────────
step "7. Django migrate & collectstatic"
# ─────────────────────────────────────────────────────────────────────────────
sudo -u "$APP_USER" bash -c "
    cd '${APP_DIR}'
    venv/bin/python manage.py migrate --noinput
    venv/bin/python manage.py collectstatic --noinput
"
ok "Migrations and static files done"

# ─────────────────────────────────────────────────────────────────────────────
step "8. Nginx configuration"
# ─────────────────────────────────────────────────────────────────────────────
NGINX_CONF="/etc/nginx/sites-available/soc-dashboard"
cat > "$NGINX_CONF" <<EOF
server {
    listen ${DASHBOARD_PORT};
    listen [::]:${DASHBOARD_PORT};
    server_name _;

    client_max_body_size 10M;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:${GUNICORN_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;
    }
}
EOF

# Enable site
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/soc-dashboard
# Disable default site if exists
rm -f /etc/nginx/sites-enabled/default

systemctl enable --now nginx
nginx -t && systemctl reload nginx
ok "Nginx configured on port ${DASHBOARD_PORT}"

# ─────────────────────────────────────────────────────────────────────────────
step "9. Firewall (ufw)"
# ─────────────────────────────────────────────────────────────────────────────
if command -v ufw &>/dev/null; then
    ufw allow "${DASHBOARD_PORT}/tcp" &>/dev/null || true
    ufw allow 'OpenSSH' &>/dev/null || true
    # Enable ufw if not active (requires confirmation bypass)
    ufw --force enable &>/dev/null || true
    ok "Firewall: port ${DASHBOARD_PORT} opened"
else
    warn "ufw not found — เปิด port ${DASHBOARD_PORT} ด้วยตนเอง"
fi

# ─────────────────────────────────────────────────────────────────────────────
step "10. systemd services"
# ─────────────────────────────────────────────────────────────────────────────

# soc-dashboard (Gunicorn)
cat > /etc/systemd/system/soc-dashboard.service <<EOF
[Unit]
Description=SOC Dashboard (Django/Gunicorn)
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/gunicorn \\
    --bind 127.0.0.1:${GUNICORN_PORT} \\
    --workers 3 \\
    --timeout 120 \\
    --access-logfile - \\
    --error-logfile - \\
    --log-level info \\
    config.wsgi:application
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soc-dashboard

[Install]
WantedBy=multi-user.target
EOF

# soc-fetcher
cat > /etc/systemd/system/soc-fetcher.service <<EOF
[Unit]
Description=SOC Dashboard Wazuh Fetcher
After=network.target soc-dashboard.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/python -u manage.py run_fetcher --interval 60
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soc-fetcher

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now soc-dashboard
systemctl enable --now soc-fetcher
ok "systemd services enabled and started"

# ─────────────────────────────────────────────────────────────────────────────
step "11. Ollama (AI Analysis)"
# ─────────────────────────────────────────────────────────────────────────────
if [[ "${INSTALL_OLLAMA,,}" == "y" ]]; then
    if ! command -v ollama &>/dev/null; then
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installed"
    else
        ok "Ollama already installed"
    fi
    systemctl enable --now ollama

    read -rp "Pull Ollama model? (e.g. qwen2.5:1.5b, openchat, leave blank to skip): " OLLAMA_MODEL
    if [[ -n "$OLLAMA_MODEL" ]]; then
        sudo -u "$APP_USER" ollama pull "$OLLAMA_MODEL" || \
            ollama pull "$OLLAMA_MODEL" || \
            warn "ollama pull failed — ลอง pull ด้วยตนเองภายหลัง"
    fi
else
    info "ข้าม Ollama — ติดตั้งทีหลังได้ด้วย: curl -fsSL https://ollama.com/install.sh | sh"
fi

# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Installation Complete!                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Dashboard URL : ${CYAN}http://${SERVER_IP}:${DASHBOARD_PORT}${NC}"
echo -e "  DB password   : ${YELLOW}${DB_PASS}${NC}  (บันทึกไว้ด้วย!)"
echo ""
echo -e "${YELLOW}สิ่งที่ต้องทำต่อ:${NC}"
echo "  1. สร้าง superuser:"
echo "     sudo -u ${APP_USER} bash -c 'cd ${APP_DIR} && venv/bin/python manage.py createsuperuser'"
echo ""
echo "  2. ตรวจสอบ services:"
echo "     systemctl status soc-dashboard soc-fetcher nginx postgresql redis-server"
echo ""
echo "  3. ดู log:"
echo "     journalctl -u soc-dashboard -f"
echo "     journalctl -u soc-fetcher -f"
echo ""
echo "  4. ตั้งค่า Wazuh/Ollama/MOPH ใน Settings หน้าเว็บ"
