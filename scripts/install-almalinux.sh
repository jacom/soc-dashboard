#!/usr/bin/env bash
# =============================================================================
# SOC Dashboard — AlmaLinux 9 / Rocky Linux 9 / RHEL 9 Installation Script
# รันด้วย: sudo bash install-almalinux.sh
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

# ── Detect source directory ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_SRC="$(dirname "$SCRIPT_DIR")"

# ── Prompt for config ──────────────────────────────────────────────────────────
echo -e "\n${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║    SOC Dashboard — AlmaLinux Installer       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}\n"

read -rp "App user (default: soc): " APP_USER
APP_USER="${APP_USER:-soc}"

read -rp "Install path (default: /home/${APP_USER}/soc-dashboard): " APP_DIR
APP_DIR="${APP_DIR:-/home/${APP_USER}/soc-dashboard}"

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
dnf install -y epel-release
dnf update -y -q
dnf install -y \
    python3.11 python3.11-pip python3.11-devel \
    postgresql-server postgresql-contrib \
    redis \
    nginx \
    git gcc \
    curl openssl \
    policycoreutils-python-utils   # สำหรับ semanage

ok "System packages installed"

# ─────────────────────────────────────────────────────────────────────────────
step "2. PostgreSQL"
# ─────────────────────────────────────────────────────────────────────────────
PG_DATA="/var/lib/pgsql/data"

# Initialize DB cluster ถ้ายังไม่มี
if [[ ! -f "${PG_DATA}/PG_VERSION" ]]; then
    postgresql-setup --initdb
    ok "PostgreSQL cluster initialized"
else
    ok "PostgreSQL cluster already exists"
fi

# แก้ pg_hba.conf: เปลี่ยน ident → md5 สำหรับ TCP connection
PG_HBA="${PG_DATA}/pg_hba.conf"
if grep -q "ident\|peer" "$PG_HBA"; then
    # Backup
    cp "${PG_HBA}" "${PG_HBA}.bak.$(date +%Y%m%d%H%M%S)"
    # เปลี่ยน ident และ peer (สำหรับ host lines) เป็น md5
    sed -i 's/^\(host[[:space:]].*\)ident$/\1md5/' "$PG_HBA"
    sed -i 's/^\(local[[:space:]].*all[[:space:]].*all[[:space:]]\+\)peer$/\1md5/' "$PG_HBA"
    ok "pg_hba.conf: เปลี่ยน auth method เป็น md5"
fi

# เพิ่ม host entry สำหรับ 127.0.0.1 ถ้ายังไม่มี
if ! grep -q "^host.*127.0.0.1" "$PG_HBA"; then
    echo "host    all             all             127.0.0.1/32            md5" >> "$PG_HBA"
    ok "pg_hba.conf: เพิ่ม host 127.0.0.1 md5"
fi

systemctl enable --now postgresql

# สร้าง DB user และ database
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
systemctl enable --now redis
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

# Copy project files
if [[ "$PROJECT_SRC" != "$APP_DIR" && -f "$PROJECT_SRC/manage.py" ]]; then
    info "Copying project files from ${PROJECT_SRC} → ${APP_DIR}"
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

# Remove default welcome page
rm -f /etc/nginx/conf.d/default.conf

systemctl enable --now nginx
nginx -t && systemctl reload nginx
ok "Nginx configured on port ${DASHBOARD_PORT}"

# ─────────────────────────────────────────────────────────────────────────────
step "9. Firewall (firewall-cmd)"
# ─────────────────────────────────────────────────────────────────────────────
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-port="${DASHBOARD_PORT}/tcp"
    # เพิ่ม Gunicorn port ใน SELinux (ขั้นตอน 10)
    firewall-cmd --reload
    ok "Firewall: port ${DASHBOARD_PORT} opened"
else
    warn "firewalld ไม่ได้รัน — ข้าม firewall config"
fi

# ─────────────────────────────────────────────────────────────────────────────
step "10. SELinux"
# ─────────────────────────────────────────────────────────────────────────────
if command -v getenforce &>/dev/null && [[ "$(getenforce)" != "Disabled" ]]; then
    info "SELinux mode: $(getenforce)"

    # อนุญาต nginx proxy ไปยัง gunicorn
    setsebool -P httpd_can_network_connect 1
    ok "SELinux: httpd_can_network_connect=1"

    # เพิ่ม port ใน SELinux http_port_t
    for PORT in "${DASHBOARD_PORT}" "${GUNICORN_PORT}"; do
        if ! semanage port -l | grep -q "http_port_t.*${PORT}"; then
            semanage port -a -t http_port_t -p tcp "${PORT}" && \
                ok "SELinux: port ${PORT} added to http_port_t" || \
                warn "SELinux: port ${PORT} อาจมีอยู่แล้ว"
        else
            ok "SELinux: port ${PORT} already in http_port_t"
        fi
    done

    # อนุญาต nginx อ่าน static files จาก /home/
    if [[ "$APP_DIR" == /home/* ]]; then
        chcon -R -t httpd_sys_content_t "${APP_DIR}/staticfiles/" 2>/dev/null || true
        ok "SELinux: staticfiles context set to httpd_sys_content_t"
        # ทำให้ persistent ด้วย semanage fcontext
        semanage fcontext -a -t httpd_sys_content_t "${APP_DIR}/staticfiles(/.*)?" 2>/dev/null || true
    fi
else
    info "SELinux disabled หรือไม่พบ — ข้าม"
fi

# ─────────────────────────────────────────────────────────────────────────────
step "11. systemd services"
# ─────────────────────────────────────────────────────────────────────────────

# soc-dashboard (Gunicorn)
cat > /etc/systemd/system/soc-dashboard.service <<EOF
[Unit]
Description=SOC Dashboard (Django/Gunicorn)
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

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
step "12. Ollama (AI Analysis)"
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
echo "     systemctl status soc-dashboard soc-fetcher nginx postgresql redis"
echo ""
echo "  3. ดู log:"
echo "     journalctl -u soc-dashboard -f"
echo "     journalctl -u soc-fetcher -f"
echo ""
echo "  4. ถ้า 502 Bad Gateway:"
echo "     sudo setsebool -P httpd_can_network_connect 1"
echo "     sudo ausearch -m avc -ts recent | tail -20"
echo ""
echo "  5. ตั้งค่า Wazuh/Ollama/MOPH ใน Settings หน้าเว็บ"
