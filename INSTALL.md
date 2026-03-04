# SOC Dashboard — Installation Guide

## Stack
- **Python 3.11+** + Django 5.1
- **PostgreSQL** — database
- **Redis** — cache/session
- **Gunicorn** — WSGI server
- **Nginx** — reverse proxy (port 8500)
- **Ollama** — local LLM (AI analysis)
- **systemd** — soc-dashboard.service, soc-fetcher.service

---

## AlmaLinux 9

### 1. System packages
```bash
sudo dnf update -y
sudo dnf install -y epel-release
sudo dnf install -y python3.11 python3.11-pip python3.11-devel \
    postgresql-server postgresql-contrib \
    redis nginx git gcc
```

### 2. PostgreSQL
```bash
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql

sudo -u postgres psql << 'EOF'
CREATE USER soc_user WITH PASSWORD 'soc_password';
CREATE DATABASE soc_db OWNER soc_user;
GRANT ALL PRIVILEGES ON DATABASE soc_db TO soc_user;
EOF
```

แก้ไข auth method (ให้ใช้ md5 แทน ident):
```bash
sudo sed -i 's/^host.*all.*all.*ident/host    all             all             127.0.0.1\/32            md5/' \
    /var/lib/pgsql/data/pg_hba.conf
sudo systemctl restart postgresql
```

### 3. Redis
```bash
sudo systemctl enable --now redis
```

### 4. Nginx
```bash
sudo systemctl enable --now nginx
# AlmaLinux ใช้ /etc/nginx/conf.d/
sudo cp soc-dashboard.conf /etc/nginx/conf.d/soc-dashboard.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Firewall
```bash
sudo firewall-cmd --permanent --add-port=8500/tcp
sudo firewall-cmd --reload
```

### 6. SELinux (สำคัญมาก!)
```bash
# อนุญาต nginx proxy ไปยัง gunicorn
sudo setsebool -P httpd_can_network_connect 1

# ถ้าใช้ port อื่นนอกจาก 80/443
sudo semanage port -a -t http_port_t -p tcp 8500
sudo semanage port -a -t http_port_t -p tcp 8002
```

> ข้ามไป **ขั้นตอนที่ใช้ร่วมกัน** ด้านล่าง

---

## Ubuntu 22.04 / 24.04

### 1. System packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib \
    redis-server nginx git build-essential libpq-dev
```

### 2. PostgreSQL
```bash
sudo systemctl enable --now postgresql

sudo -u postgres psql << 'EOF'
CREATE USER soc_user WITH PASSWORD 'soc_password';
CREATE DATABASE soc_db OWNER soc_user;
GRANT ALL PRIVILEGES ON DATABASE soc_db TO soc_user;
EOF
```

### 3. Redis
```bash
sudo systemctl enable --now redis-server
```

### 4. Nginx
```bash
sudo systemctl enable --now nginx
# Ubuntu ใช้ sites-available/sites-enabled
sudo cp soc-dashboard.conf /etc/nginx/sites-available/soc-dashboard
sudo ln -s /etc/nginx/sites-available/soc-dashboard /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Firewall
```bash
sudo ufw allow 8500/tcp
sudo ufw reload
```

> ข้ามไป **ขั้นตอนที่ใช้ร่วมกัน** ด้านล่าง

---

## ขั้นตอนที่ใช้ร่วมกัน (AlmaLinux + Ubuntu)

### 1. สร้าง user และโครงสร้างโฟลเดอร์
```bash
sudo useradd -m -s /bin/bash soc
sudo mkdir -p /home/soc/soc-dashboard
sudo chown soc:soc /home/soc/soc-dashboard
sudo su - soc
```

### 2. Clone / copy project
```bash
cd /home/soc
# วิธีที่ 1: Copy จากเครื่องเก่า
scp -r jong2@<OLD_SERVER>:/home/jong2/soc-dashboard/* /home/soc/soc-dashboard/

# วิธีที่ 2: Clone จาก git (ถ้ามี)
# git clone <repo-url> soc-dashboard
```

### 3. Python virtualenv
```bash
cd /home/soc/soc-dashboard
python3.11 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### 4. ตั้งค่า .env
```bash
cp .env .env.backup
nano .env
```

แก้ค่าให้ตรงกับ server ใหม่:
```env
SECRET_KEY=<สุ่มค่าใหม่ยาวๆ เช่น python3 -c "import secrets; print(secrets.token_hex(50))">
DEBUG=False
ALLOWED_HOSTS=<IP_SERVER>,localhost,127.0.0.1

CSRF_TRUSTED_ORIGINS=http://<IP_SERVER>:8500

DATABASE_URL=postgresql://soc_user:soc_password@127.0.0.1:5432/soc_db

REDIS_URL=redis://127.0.0.1:6379/1

DJANGO_DASHBOARD_URL=http://<IP_SERVER>:8500
SOC_BOT_API_TOKEN=<token เดิมหรือสร้างใหม่>
```

### 5. Migrate & Static files
```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py createsuperuser
```

### 6. นำข้อมูลจาก server เก่า (optional)
```bash
# Export จาก server เก่า
# (บน server เก่า)
venv/bin/python manage.py dumpdata --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission \
    --indent 2 > backup.json

# Import ใน server ใหม่
venv/bin/python manage.py loaddata backup.json
```

### 7. ติดตั้ง systemd services

**soc-dashboard (Gunicorn):**
```bash
# แก้ User=jong2 → User=soc และ path ให้ถูกต้อง
sudo cp soc-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now soc-dashboard
```

**soc-fetcher:**
```bash
sudo cp /etc/systemd/system/soc-fetcher.service /tmp/soc-fetcher.service
# แก้ User และ path
sudo nano /tmp/soc-fetcher.service
sudo cp /tmp/soc-fetcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now soc-fetcher
```

### 8. ติดตั้ง Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama

# pull model ที่ใช้ (ดูจาก Settings > Ollama)
ollama pull qwen2.5:1.5b
# หรือ
ollama pull openchat
```

### 9. ตรวจสอบ
```bash
sudo systemctl status soc-dashboard soc-fetcher nginx postgresql redis
journalctl -u soc-dashboard -f
journalctl -u soc-fetcher -f
```

---

## สรุป Services

| Service | Port | หน้าที่ |
|---------|------|---------|
| nginx | 8500 | Reverse proxy |
| gunicorn (soc-dashboard) | 8002 | Django app |
| soc-fetcher | — | Fetch Wazuh ทุก 60s |
| postgresql | 5432 | Database |
| redis | 6379 | Cache |
| ollama | 11434 | Local LLM |
| thehive | 9009 | Incident management |

---

## ความแตกต่างหลัก AlmaLinux vs Ubuntu

| | AlmaLinux 9 | Ubuntu 22/24 |
|--|-------------|--------------|
| Package mgr | `dnf` | `apt` |
| Redis service | `redis` | `redis-server` |
| Nginx config | `/etc/nginx/conf.d/` | `/etc/nginx/sites-available/` |
| SELinux | **ต้อง config** | ไม่มี |
| Firewall | `firewall-cmd` | `ufw` |
| Python | `python3.11` | `python3.11` |
| pg_hba.conf | `/var/lib/pgsql/data/` | `/etc/postgresql/*/main/` |

---

## AlmaLinux SELinux — ปัญหาที่พบบ่อย

```bash
# ถ้า 502 Bad Gateway
sudo setsebool -P httpd_can_network_connect 1

# ถ้า static files 403
sudo chcon -R -t httpd_sys_content_t /home/soc/soc-dashboard/staticfiles/

# ดู SELinux denials
sudo ausearch -m avc -ts recent | tail -20
```
