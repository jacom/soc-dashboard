# Changelog

All notable changes to SOC Dashboard will be documented here.
Format: [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`

---

## [1.0.0] - 2026-03-02

### Added
- Authentication system — login_required ทุก view, dark-theme login page
- Incident `approved_by` — บันทึกว่าใคร approve incident
- Universal install script (`scripts/install.sh`) รองรับ Ubuntu 22/24 และ AlmaLinux 9
- AI analysis ด้วย Ollama (background thread)
- Chat AI analysis ด้วย OpenAI-compatible API
- TheHive integration — push alert เป็น case
- LINE Notify & MOPH Notify alerts
- Wazuh webhook receiver (`/api/alerts/wazuh-webhook/`)
- Version display ใน sidebar

### Core Features
- Dashboard พร้อม hourly timeline chart, top rules, recent critical alerts
- Alert list พร้อม filter, sort, pagination
- Incident management (New / InProgress / Resolved / Closed)
- Notification log (LINE, MOPH)
- Integration Settings UI (Wazuh, Ollama, TheHive, LINE, MOPH)
