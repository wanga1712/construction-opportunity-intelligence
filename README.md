# Construction Opportunity Intelligence

Система автоматического анализа тендерной документации для поиска интересных закупок по строительным материалам.

## Архитектура

```
Сервер 7 (S7)          Сервер 13 (S13)
─────────────────────         ─────────────────────────────────
PostgreSQL 17                 5 демонов (workers 13-17)
  ├── tender_monitor (5GB)    Ollama qwen2.5:7b (классификатор)
  └── crm (28MB)              CRM Streamlit :8504
EIS-парсеры (44-ФЗ, 223-ФЗ)
```

## Компоненты

| Директория | Описание |
|---|---|
| `tender_documents_research/` | Ядро: демоны, классификатор, матчер, парсеры |
| `crm_streamlit/` | CRM-система на Streamlit |
| `deploy/systemd/` | systemd unit-файлы (11 сервисов) |
| `deploy/scripts/` | Скрипты `/usr/local/bin/` (метрики, алерты, шатдаун) |
| `deploy/env_templates/` | Шаблоны env-файлов (пароли заменены на `${DB_PASSWORD}`) |
| `database/` | Схемы БД: tender_monitor + crm (без данных) |

## Быстрое восстановление

### Предварительные требования
- Сервер с Ubuntu 22.04+, 16+ GB RAM, Python 3.10+
- PostgreSQL 17 (сервер 7)
- Ollama с моделью qwen2.5:7b

### Шаги
```bash
# 1. Клонировать репо
git clone https://github.com/wanga1712/construction-opportunity-intelligence.git
cd construction-opportunity-intelligence

# 2. Развернуть схемы БД
psql -h <S7_DB_HOST> -U postgres -d tender_monitor < database/tender_monitor_schema.sql
psql -h <S7_DB_HOST> -U postgres -d crm < database/crm_schema.sql

# 3. Настроить env-файлы
cp deploy/env_templates/tender-docs-db.env.template /etc/tender-docs-db.env
# Заменить ${DB_PASSWORD} на реальный пароль

# 4. Установить venv
python3 -m venv /opt/tender_documents_research/.venv
/opt/tender_documents_research/.venv/bin/pip install -r tender_documents_research/requirements.txt

# 5. Развернуть systemd-сервисы
cp deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tender-docs-daemon-open tender-docs-daemon-awarded

# 6. Настроить cron (root)
# * * * * * /usr/local/bin/temp_shutdown_guard.sh
# 0 23 * * * /sbin/shutdown -h now
```

## Статус (2026-08-03)
- 5 демонов активны (workers 13-17)
- 538 контрактов в очереди pending
- 252 completed, 1651 матчей найдено
- Классификатор: 8382 контрактов в кеше

## Подключение к серверам
```bash
# Сервер 7
ssh -i ~/.ssh/<SSH_IDENTITY> <S7_SSH_USER>@S7

# Сервер 13 (через ProxyJump)
ssh -i ~/.ssh/<SSH_IDENTITY> -o ProxyJump=<S7_SSH_USER>@S7 <S13_SSH_USER>@S13
```
