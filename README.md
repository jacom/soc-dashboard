# SOC Dashboard

ระบบ Security Operations Center Dashboard สำหรับโรงพยาบาลวานรนิวาส
รองรับ Wazuh, TheHive, Ollama, OpenAI, LINE Notify, MOPH Notify

**Version:** 1.1.0

---

## Requirements

- Python 3.11+ / Docker
- PostgreSQL 15+
- Redis 7+
- Wazuh Indexer (OpenSearch) 2.x

---

## วิธีติดตั้ง

### แบบที่ 1 — Docker Compose (แนะนำ)

```bash
git clone https://github.com/jacom/soc-dashboard.git
cd soc-dashboard
sudo bash scripts/init.sh
```

Script จะ:
- Auto-generate `SECRET_KEY`, `DB_PASSWORD`, detect IP เครื่องให้อัตโนมัติ
- ถามแค่ **Wazuh Indexer URL** และ **Password**
- รัน `docker compose up`, migrate, collectstatic, createsuperuser ให้ครบ

---

### แบบที่ 2 — Script ติดตั้งบน Server (Ubuntu / AlmaLinux)

```bash
# Ubuntu 22.04 / 24.04 หรือ AlmaLinux 9 / Rocky Linux 9
curl -fsSL https://raw.githubusercontent.com/jacom/soc-dashboard/main/scripts/install.sh | sudo bash
```

หรือรันจากไฟล์:

```bash
sudo bash scripts/install.sh
```

Script จะติดตั้งและตั้งค่าให้อัตโนมัติ:
- Python 3.11, PostgreSQL 15, Redis, Nginx, Gunicorn
- สร้าง `.env`, migrate database, collectstatic
- ตั้งค่า systemd service และ Nginx

---

## อัปเดต

### Docker
```bash
bash scripts/update.sh --docker
```

### Non-Docker
```bash
bash scripts/update.sh
```

หรือกดปุ่ม **Update** บนหน้า Dashboard เมื่อมี version ใหม่

---

## การตั้งค่าหลังติดตั้ง

1. เข้า `/settings/` — กรอก Wazuh, LINE, SMTP และ integration อื่นๆ
2. เข้า `/settings/wazuh-check/` — ตรวจสอบ Wazuh config และ index
3. เข้า `/license/` — ใส่ License Key ที่ได้รับจาก vendor
4. เข้า `/2fa/setup/` — เปิดใช้ Two-Factor Authentication (optional)

---

## Stack

| Component | Technology |
|-----------|-----------|
| Backend | Django 5.1 + Gunicorn |
| Database | PostgreSQL 15 |
| Cache | Redis 7 |
| Frontend | Bootstrap 5.3 + Chart.js |
| SIEM | Wazuh 4.x |
| AI | Ollama / OpenAI-compatible |
| Notification | LINE Notify, MOPH Notify, SMTP |

---

© 2026 โรงพยาบาลวานรนิวาส SOC Dashboard. All rights reserved.
