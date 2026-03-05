#!/usr/bin/env bash
# =============================================================================
# SOC Dashboard — Universal Installer
# รองรับ: Ubuntu 22.04/24.04 | AlmaLinux 9 / Rocky Linux 9 / RHEL 9
#
# วิธีใช้ (GitHub):
#   curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/soc-dashboard/main/scripts/install.sh | sudo bash
#
# หรือรันจาก local:
#   sudo bash scripts/install.sh
# =============================================================================
set -euo pipefail

# ── GitHub config (แก้ตรงนี้ก่อน release) ─────────────────────────────────
GITHUB_REPO="jacom/SOC-Dashboard"
GITHUB_BRANCH="main"
# ─────────────────────────────────────────────────────────────────────────────

# ── Colors & helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step() {
    echo -e "\n${BLUE}══════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $*${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════${NC}"
}

# ── Pre-flight ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && err "กรุณารันด้วย sudo: sudo bash $0"

# ── OS Detection ─────────────────────────────────────────────────────────────
if [[ ! -f /etc/os-release ]]; then
    err "ไม่พบ /etc/os-release — ไม่สามารถตรวจสอบ OS ได้"
fi

. /etc/os-release
OS_ID="${ID,,}"         # ubuntu, almalinux, rocky, rhel, centos ...
OS_VER="${VERSION_ID}"

case "$OS_ID" in
    ubuntu|debian)
        OS_FAMILY="debian"
        info "Detected OS: ${PRETTY_NAME}"
        ;;
    almalinux|rocky|rhel|centos)
        OS_FAMILY="rhel"
        info "Detected OS: ${PRETTY_NAME}"
        ;;
    *)
        err "OS ไม่รองรับ: ${PRETTY_NAME}\nรองรับเฉพาะ Ubuntu 22/24 และ AlmaLinux/Rocky 9"
        ;;
esac

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║         SOC Dashboard — Installer            ║${NC}"
echo -e "${CYAN}║  OS: $(printf '%-38s' "${PRETTY_NAME}")║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}\n"

# ── Detect if running via curl (no local project files) ──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-/tmp}")" 2>/dev/null && pwd || echo /tmp)"
PROJECT_SRC="$(dirname "$SCRIPT_DIR")"
RUNNING_VIA_CURL=false

if [[ ! -f "$PROJECT_SRC/manage.py" ]]; then
    RUNNING_VIA_CURL=true
    info "ไม่พบ project files — จะ clone จาก GitHub"
fi

# ── Prompt for config (อ่านจาก /dev/tty เสมอ รองรับ curl | bash) ──────────────
_read() {
    local prompt="$1" varname="$2"
    printf "%s" "$prompt" > /dev/tty
    read -r "$varname" < /dev/tty
}

_read "App user (default: soc): " APP_USER
APP_USER="${APP_USER:-soc}"

_read "Install path (default: /home/${APP_USER}/soc-dashboard): " APP_DIR
APP_DIR="${APP_DIR:-/home/${APP_USER}/soc-dashboard}"

DEFAULT_IP=$(hostname -I | awk '{print $1}')
_read "Server IP (default: ${DEFAULT_IP}): " SERVER_IP
SERVER_IP="${SERVER_IP:-$DEFAULT_IP}"

_read "Dashboard port (default: 8500): " DASHBOARD_PORT
DASHBOARD_PORT="${DASHBOARD_PORT:-8500}"

_read "Gunicorn port (default: 8002): " GUNICORN_PORT
GUNICORN_PORT="${GUNICORN_PORT:-8002}"

_read "DB name (default: soc_db): " DB_NAME
DB_NAME="${DB_NAME:-soc_db}"

_read "DB user (default: soc_user): " DB_USER
DB_USER="${DB_USER:-soc_user}"

_read "DB password (leave blank to auto-generate): " DB_PASS
if [[ -z "$DB_PASS" ]]; then
    DB_PASS=$(openssl rand -hex 16)
    info "Generated DB password: ${DB_PASS}"
fi

SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(50))" 2>/dev/null \
             || openssl rand -hex 50)

_read "Install Ollama for AI analysis? [y/N]: " INSTALL_OLLAMA
INSTALL_OLLAMA="${INSTALL_OLLAMA:-n}"

echo ""
info "Configuration summary:"
echo "  OS          : ${PRETTY_NAME}"
echo "  App user    : ${APP_USER}"
echo "  Install dir : ${APP_DIR}"
echo "  Server IP   : ${SERVER_IP}"
echo "  Port        : ${DASHBOARD_PORT}"
echo "  DB          : ${DB_NAME} / ${DB_USER}"
echo ""
_read "Proceed with installation? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" != "y" ]] && echo "Aborted." && exit 0

# =============================================================================
# STEP 1 — System Packages
# =============================================================================
step "1. System packages"

if [[ "$OS_FAMILY" == "debian" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q \
        python3.11 python3.11-venv python3.11-dev \
        postgresql postgresql-contrib \
        redis-server \
        nginx \
        git build-essential libpq-dev \
        curl openssl
    REDIS_SERVICE="redis-server"
    PYTHON_BIN="python3.11"

elif [[ "$OS_FAMILY" == "rhel" ]]; then
    dnf install -y epel-release
    dnf update -y -q
    dnf install -y \
        python3.11 python3.11-pip python3.11-devel \
        postgresql-server postgresql-contrib \
        redis \
        nginx \
        git gcc \
        curl openssl \
        policycoreutils-python-utils
    REDIS_SERVICE="redis"
    PYTHON_BIN="python3.11"
fi

ok "System packages installed"

# =============================================================================
# STEP 2 — PostgreSQL
# =============================================================================
step "2. PostgreSQL"

if [[ "$OS_FAMILY" == "rhel" ]]; then
    PG_DATA="/var/lib/pgsql/data"
    if [[ ! -f "${PG_DATA}/PG_VERSION" ]]; then
        postgresql-setup --initdb
        ok "PostgreSQL cluster initialized"
    else
        ok "PostgreSQL cluster already exists"
    fi

    # เปลี่ยน ident/peer → md5
    PG_HBA="${PG_DATA}/pg_hba.conf"
    if grep -q "ident\|peer" "$PG_HBA"; then
        cp "${PG_HBA}" "${PG_HBA}.bak.$(date +%Y%m%d%H%M%S)"
        sed -i 's/^\(host[[:space:]].*\)ident$/\1md5/'  "$PG_HBA"
        sed -i 's/^\(local[[:space:]].*all[[:space:]].*all[[:space:]]\+\)peer$/\1md5/' "$PG_HBA"
        ok "pg_hba.conf: auth method → md5"
    fi
    if ! grep -q "^host.*127.0.0.1" "$PG_HBA"; then
        echo "host    all             all             127.0.0.1/32            md5" >> "$PG_HBA"
        ok "pg_hba.conf: เพิ่ม host 127.0.0.1"
    fi
fi

systemctl enable --now postgresql

cd /tmp && sudo -u postgres psql -v ON_ERROR_STOP=0 <<SQL
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

ok "PostgreSQL: '${DB_NAME}' / '${DB_USER}' ready"

# =============================================================================
# STEP 3 — Redis
# =============================================================================
step "3. Redis"
systemctl enable --now "${REDIS_SERVICE}"
redis-cli ping | grep -q PONG && ok "Redis is running" || warn "Redis ping failed"

# =============================================================================
# STEP 4 — App user & project files
# =============================================================================
step "4. App user and project files"

if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$APP_USER"
    ok "Created user: ${APP_USER}"
else
    ok "User '${APP_USER}' already exists"
fi

mkdir -p "$APP_DIR"
chown "${APP_USER}:${APP_USER}" "$APP_DIR"

if [[ "$RUNNING_VIA_CURL" == true ]]; then
    # Clone จาก GitHub
    if ! command -v git &>/dev/null; then
        err "ไม่พบ git — กรุณาติดตั้ง git ก่อน"
    fi
    info "Cloning from https://github.com/${GITHUB_REPO} ..."
    sudo -u "$APP_USER" git clone \
        --depth=1 \
        --branch "${GITHUB_BRANCH}" \
        "https://github.com/${GITHUB_REPO}.git" \
        "${APP_DIR}"
    ok "Cloned to ${APP_DIR}"

elif [[ "$PROJECT_SRC" != "$APP_DIR" && -f "$PROJECT_SRC/manage.py" ]]; then
    info "Copying project files: ${PROJECT_SRC} → ${APP_DIR}"
    if command -v rsync &>/dev/null; then
        rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
              --exclude='.env' --exclude='staticfiles' \
              "${PROJECT_SRC}/" "${APP_DIR}/"
    else
        cp -a "${PROJECT_SRC}/." "${APP_DIR}/"
    fi
    chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"
    ok "Project files copied"

elif [[ -f "$APP_DIR/manage.py" ]]; then
    ok "Project files already at ${APP_DIR}"
else
    err "ไม่พบ manage.py — กรุณาตรวจสอบ GITHUB_REPO ในไฟล์นี้"
fi

# =============================================================================
# STEP 5 — Python virtualenv & dependencies
# =============================================================================
step "5. Python virtualenv & dependencies"

sudo -u "$APP_USER" bash -c "
    cd '${APP_DIR}'
    ${PYTHON_BIN} -m venv venv
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r requirements.txt -q
"
ok "Dashboard dependencies installed"

# soc-bot venv
sudo -u "$APP_USER" bash -c "
    cd '${APP_DIR}/soc-bot'
    ${PYTHON_BIN} -m venv venv
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r requirements.txt -q
"
ok "soc-bot dependencies installed"

# =============================================================================
# STEP 6 — .env file
# =============================================================================
step "6. Create .env file"

ENV_FILE="${APP_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists — writing .env.new (ไม่ทับของเดิม)"
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
ok "Dashboard .env created at ${ENV_FILE}"

# soc-bot .env
BOT_ENV_FILE="${APP_DIR}/soc-bot/.env"
if [[ -f "$BOT_ENV_FILE" ]]; then
    warn "soc-bot .env already exists — ข้าม"
else
cat > "$BOT_ENV_FILE" <<EOF
# Wazuh API
WAZUH_API_URL=
WAZUH_USER=wazuh
WAZUH_PASSWORD=

# Ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=openchat

# TheHive (set to empty string to disable)
THEHIVE_URL=
THEHIVE_API_KEY=

# LINE Notify (set to empty string to disable)
LINE_NOTIFY_TOKEN=

# SOC Dashboard API
DASHBOARD_URL=http://${SERVER_IP}:${DASHBOARD_PORT}
DASHBOARD_API_TOKEN=

# Redis (for deduplication state)
REDIS_URL=redis://127.0.0.1:6379/2

# Polling interval in seconds
POLL_INTERVAL=30

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO
EOF
    chown "${APP_USER}:${APP_USER}" "$BOT_ENV_FILE"
    chmod 640 "$BOT_ENV_FILE"
    ok "soc-bot .env created at ${BOT_ENV_FILE}"
fi

# =============================================================================
# STEP 7 — Django migrate & collectstatic
# =============================================================================
step "7. Django migrate & collectstatic"

sudo -u "$APP_USER" bash -c "
    cd '${APP_DIR}'
    venv/bin/python manage.py migrate --noinput
    venv/bin/python manage.py collectstatic --noinput
"
ok "Migrations and static files done"

# =============================================================================
# STEP 8 — Nginx
# =============================================================================
step "8. Nginx configuration"

if [[ "$OS_FAMILY" == "debian" ]]; then
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
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/soc-dashboard
    rm -f /etc/nginx/sites-enabled/default

elif [[ "$OS_FAMILY" == "rhel" ]]; then
    NGINX_CONF="/etc/nginx/conf.d/soc-dashboard.conf"
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
    rm -f /etc/nginx/conf.d/default.conf
fi

systemctl enable --now nginx
nginx -t && systemctl reload nginx
ok "Nginx configured on port ${DASHBOARD_PORT}"

# =============================================================================
# STEP 9 — Firewall
# =============================================================================
step "9. Firewall"

if [[ "$OS_FAMILY" == "debian" ]]; then
    if command -v ufw &>/dev/null; then
        ufw allow "${DASHBOARD_PORT}/tcp" &>/dev/null || true
        ufw allow 'OpenSSH'              &>/dev/null || true
        ufw --force enable               &>/dev/null || true
        ok "ufw: port ${DASHBOARD_PORT} opened"
    else
        warn "ufw ไม่พบ — เปิด port ${DASHBOARD_PORT} ด้วยตนเอง"
    fi

elif [[ "$OS_FAMILY" == "rhel" ]]; then
    if systemctl is-active --quiet firewalld; then
        firewall-cmd --permanent --add-port="${DASHBOARD_PORT}/tcp"
        firewall-cmd --reload
        ok "firewalld: port ${DASHBOARD_PORT} opened"
    else
        warn "firewalld ไม่ได้รัน — ข้าม firewall config"
    fi
fi

# =============================================================================
# STEP 10 — SELinux (RHEL only)
# =============================================================================
if [[ "$OS_FAMILY" == "rhel" ]]; then
    step "10. SELinux"
    if command -v getenforce &>/dev/null && [[ "$(getenforce)" != "Disabled" ]]; then
        info "SELinux mode: $(getenforce)"
        setsebool -P httpd_can_network_connect 1
        ok "SELinux: httpd_can_network_connect=1"

        for PORT in "${DASHBOARD_PORT}" "${GUNICORN_PORT}"; do
            if ! semanage port -l | grep -q "http_port_t.*${PORT}"; then
                semanage port -a -t http_port_t -p tcp "${PORT}" && \
                    ok "SELinux: port ${PORT} → http_port_t" || \
                    warn "SELinux: port ${PORT} อาจมีอยู่แล้ว"
            else
                ok "SELinux: port ${PORT} already in http_port_t"
            fi
        done

        if [[ "$APP_DIR" == /home/* ]]; then
            chcon -R -t httpd_sys_content_t "${APP_DIR}/staticfiles/" 2>/dev/null || true
            semanage fcontext -a -t httpd_sys_content_t "${APP_DIR}/staticfiles(/.*)?" 2>/dev/null || true
            ok "SELinux: staticfiles context set"
        fi
    else
        info "SELinux disabled — ข้าม"
    fi
fi

# =============================================================================
# STEP 11 — systemd services
# =============================================================================
STEP_NUM=11
[[ "$OS_FAMILY" == "debian" ]] && STEP_NUM=10
step "${STEP_NUM}. systemd services"

REDIS_AFTER="redis-server.service"
[[ "$OS_FAMILY" == "rhel" ]] && REDIS_AFTER="redis.service"

cat > /etc/systemd/system/soc-dashboard.service <<EOF
[Unit]
Description=SOC Dashboard (Django/Gunicorn)
After=network.target postgresql.service ${REDIS_AFTER}
Wants=postgresql.service ${REDIS_AFTER}

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

cat > /etc/systemd/system/soc-bot.service <<EOF
[Unit]
Description=SOC Bot (Wazuh Alert Processor)
After=network.target ${REDIS_AFTER} soc-dashboard.service
Wants=${REDIS_AFTER}

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/soc-bot
EnvironmentFile=${APP_DIR}/soc-bot/.env
ExecStart=${APP_DIR}/soc-bot/venv/bin/python main.py
Restart=always
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soc-bot

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now soc-dashboard
systemctl enable --now soc-fetcher
systemctl enable --now soc-bot
ok "systemd services enabled and started (dashboard, fetcher, bot)"

# =============================================================================
# STEP 12 — Ollama (optional)
# =============================================================================
STEP_NUM=12
[[ "$OS_FAMILY" == "debian" ]] && STEP_NUM=11
step "${STEP_NUM}. Ollama (AI Analysis)"

if [[ "${INSTALL_OLLAMA,,}" == "y" ]]; then
    if ! command -v ollama &>/dev/null; then
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installed"
    else
        ok "Ollama already installed"
    fi
    systemctl enable --now ollama

    _read "Pull Ollama model? (e.g. qwen2.5:1.5b, openchat — leave blank to skip): " OLLAMA_MODEL
    if [[ -n "$OLLAMA_MODEL" ]]; then
        ollama pull "$OLLAMA_MODEL" || warn "ollama pull failed — ลอง pull ด้วยตนเองภายหลัง"
    fi
else
    info "ข้าม Ollama — ติดตั้งทีหลัง: curl -fsSL https://ollama.com/install.sh | sh"
fi

# =============================================================================
# Done
# =============================================================================
echo -e "\n${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Installation Complete!                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  OS            : ${CYAN}${PRETTY_NAME}${NC}"
echo -e "  Dashboard URL : ${CYAN}http://${SERVER_IP}:${DASHBOARD_PORT}${NC}"
echo -e "  DB password   : ${YELLOW}${DB_PASS}${NC}  ← บันทึกไว้ด้วย!"
echo ""
echo -e "${YELLOW}สิ่งที่ต้องทำต่อ:${NC}"
echo "  1. สร้าง superuser:"
echo "     sudo -u ${APP_USER} bash -c 'cd ${APP_DIR} && venv/bin/python manage.py createsuperuser'"
echo ""
echo "  2. กรอก DASHBOARD_API_TOKEN ใน soc-bot/.env:"
echo "     (token จาก: Django Admin → Auth Token → Add token)"
echo "     nano ${APP_DIR}/soc-bot/.env"
echo "     sudo systemctl restart soc-bot"
echo ""
echo "  3. ตรวจสอบ services:"
if [[ "$OS_FAMILY" == "debian" ]]; then
echo "     systemctl status soc-dashboard soc-fetcher soc-bot nginx postgresql redis-server"
else
echo "     systemctl status soc-dashboard soc-fetcher soc-bot nginx postgresql redis"
fi
echo ""
echo "  4. ดู log:"
echo "     journalctl -u soc-dashboard -f"
echo "     journalctl -u soc-bot -f"
echo ""
echo "  4. ตั้งค่า Wazuh/Ollama/MOPH ใน Settings หน้าเว็บ"
if [[ "$OS_FAMILY" == "rhel" ]]; then
echo ""
echo "  5. ถ้า 502 Bad Gateway:"
echo "     sudo setsebool -P httpd_can_network_connect 1"
fi
echo ""
