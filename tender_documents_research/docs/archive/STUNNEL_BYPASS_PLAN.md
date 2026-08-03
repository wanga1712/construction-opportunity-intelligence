# План обхода Stunnel для разгрузки системы

## 🚨 Проблема
- Stunnel перегружен запросами на скачивание больших файлов (200 МБ на закупку)
- Это блокирует получение XML файлов через SOAP API
- Система не обрабатывает документы уже 2 дня

## 🎯 Решение
Переключить скачивание документов на прямые HTTPS запросы с:
- Имитацией браузера (реалистичные заголовки)
- Пользовательскими сертификатами
- Stunnel остается только для XML/SOAP запросов

## 📋 Файлы для копирования на сервер nyx

```bash
scp improved_http_client.py nyx:/opt/tendermonitor/
scp patch_http_client.py nyx:/opt/tendermonitor/
scp patch_downloader.py nyx:/opt/tendermonitor/
scp deploy_stunnel_bypass.sh nyx:/opt/tendermonitor/
scp check_system_status.py nyx:/opt/tendermonitor/
scp monitor_recovery.py nyx:/opt/tendermonitor/
```

## 🔧 Команды на сервере nyx

### 1. Подключение и подготовка
```bash
ssh nyx
cd /opt/tendermonitor
```

### 2. Применение патчей (локально)
```bash
python patch_http_client.py
python patch_downloader.py
```

### 3. Развертывание на сервере
```bash
chmod +x deploy_stunnel_bypass.sh
sudo ./deploy_stunnel_bypass.sh
```

### 4. Мониторинг восстановления
```bash
# Проверка статуса системы
python check_system_status.py

# Мониторинг в реальном времени
python monitor_recovery.py

# Логи демонов
journalctl -u tender-daemon -f
```

## ⚙️ Ключевые изменения

### HTTP Client (document_processor/http_client.py)
- ✅ Реалистичные заголовки браузера
- ✅ Поддержка пользовательских сертификатов
- ✅ Понижение SSL SECLEVEL для совместимости
- ✅ Referer для zakupki.gov.ru

### Downloader (document_processor/downloader.py)
- ✅ Приоритет прямого скачивания
- ✅ Проверка размера файла перед использованием прокси
- ✅ Множественные попытки с увеличивающейся задержкой
- ✅ Stunnel только для файлов < 10 МБ

### Конфигурация (.env)
```bash
BYPASS_PROXY_FOR_LARGE_FILES=true
MAX_PROXY_FILE_SIZE=10485760  # 10 MB
CLIENT_CERT_PATH=/etc/stunnel/client.pem
DIRECT_DOWNLOAD_TIMEOUT=300
DOWNLOAD_DELAY_SECONDS=2.0
MAX_DOWNLOAD_RETRIES=3
```

## 📊 Ожидаемые результаты

### Немедленно:
- Stunnel разгружен от больших файлов
- XML/SOAP запросы проходят без задержек
- Демоны начинают добавлять новые контракты в очередь

### В течение часа:
- Появляются новые задачи в очереди
- Начинается обработка документов
- Система возвращается к нормальной работе

## 🔍 Диагностика проблем

### Если система не восстанавливается:
```bash
# Проверка сертификатов
ls -la /etc/stunnel/client.pem
openssl x509 -in /etc/stunnel/client.pem -text -noout

# Проверка подключения
curl -v --cert /etc/stunnel/client.pem https://zakupki.gov.ru/

# Логи ошибок
tail -f /var/log/tendermonitor/*.log
```

### Откат изменений:
```bash
# Восстановление из резервной копии
sudo cp /opt/tendermonitor/backups/YYYYMMDD_HHMMSS/* /opt/tendermonitor/document_processor/
sudo systemctl restart tender-daemon tender-worker
```

## 🎯 Преимущества решения

1. **Разгрузка Stunnel** - освобождается для XML запросов
2. **Повышение надежности** - прямые HTTPS соединения
3. **Лучшая совместимость** - имитация браузера
4. **Гибкость настройки** - параметры через переменные окружения
5. **Обратная совместимость** - Stunnel остается для небольших файлов

## ✅ Критерии успеха

- [ ] Новые задачи появляются в очереди
- [ ] Документы скачиваются и обрабатываются
- [ ] Stunnel показывает низкую нагрузку
- [ ] Нет ошибок "Не удалось скачать ни один документ"
- [ ] Система обрабатывает закупки на полгода вперед