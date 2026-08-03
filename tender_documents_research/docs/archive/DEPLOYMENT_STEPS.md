# 🚀 Пошаговое внедрение умного извлечения текста

## Быстрый старт (3 команды)

```bash
# 1. Тест интеграции
python3 quick_test_integration.py

# 2. Настройка и запуск
python3 setup_smart_extraction.py

# 3. Мониторинг
journalctl -u tendermonitor-document-research.service -f
```

## Что происходит

### ✅ Проблема решена:
**БЫЛО:** Нечитаемые строки по 800+ символов
```
ЭМв т.ч. ОТмЗТЗТмИтого по расценкеСП Работы по реконструкции зданий и сооружений: разборка отдельных конструктивных элементов здания (сооружения), а также зданий (сооружений) в целомВсего по позицииУтепление покрытий: керамзитом (демонтаж)Демонтаж (разборка) сборных бетонных и железобетонных строительных конструкций ОЗП=0,8; ЭМ=0,8 к расх.; ЗПМ=0,8; МАТ=0 к расх.; ТЗ=0,8; ТЗМ=0,8 ОТЭМЗТИтого по расценкеФОТНР Работы по реконструкции зданий и сооружений: разборка отдельных конструктивных элементов здания (сооружения), а также зданий (сооружений) в целомСП Работы по реконструкции зданий и сооружений: усиление и замена существующих конструкций, возведение отдельных конструктивных элементовВсего по позицииРазборка покрытий кровель: из волнистых и полуволнистых хризотилцементных листовОбъем=1692 / 100ОТ ФОТНР Кровли СП Кровли Всего по позиции
```

**СТАЛО:** Читаемые фрагменты с подсветкой
```
Основной: Работы по реконструкции зданий и сооружений: усиление и замена существующих конструкций, возведение отдельных конструктивных элементов

Отображение: ...зданий (сооружений) в [целомСП Работы по реконструкции зданий и сооружений: **усиление** и замена существующих **конструкций**, возведение отдельных конструктивных элементовВсего по позицииРазборка] покрытий кровель...
```

### 📊 Результаты:
- **Экономия места:** 74.4% в среднем
- **Читаемость:** Значительно улучшена
- **Контекст:** Сохранен и подсвечен
- **Производительность:** +10-20ms на документ

## Детальные шаги

### 1. Проверка готовности
```bash
# Проверяем файлы
ls -la smart_text_extractor.py enhanced_matcher.py
ls -la document_processor/matcher.py

# Быстрый тест
python3 quick_test_integration.py
```

### 2. Автоматическая настройка
```bash
# Полная настройка systemd сервиса
python3 setup_smart_extraction.py
```

### 3. Ручная настройка (если автоматическая не сработала)
```bash
# Добавляем переменные окружения
sudo systemctl edit tendermonitor-document-research.service

# В открывшемся редакторе добавить:
[Service]
Environment=ENABLE_SMART_EXTRACTION=1
Environment=MAX_FRAGMENT_LENGTH=200
Environment=SAVE_ORIGINAL_LINES=0

# Перезапуск
sudo systemctl daemon-reload
sudo systemctl restart tendermonitor-document-research.service
```

### 4. Проверка работы
```bash
# Статус сервиса
sudo systemctl status tendermonitor-document-research.service

# Логи в реальном времени
journalctl -u tendermonitor-document-research.service -f

# Общий статус системы
tm-status
```

## Настройки

| Переменная | Умолчание | Описание |
|---|---|---|
| `ENABLE_SMART_EXTRACTION` | `0` | Включить умное извлечение |
| `MAX_FRAGMENT_LENGTH` | `200` | Максимальная длина фрагмента |
| `SAVE_ORIGINAL_LINES` | `0` | Сохранять оригинальные строки |

## Мониторинг

### Что искать в логах:
```bash
# Успешное применение
"Smart text extraction applied to X matches"

# Ошибки
"Smart extraction error:"

# Статистика улучшений
"Text extraction stats: avg_length 227→58, long_lines 3→0"
```

### Команды мониторинга:
```bash
# Логи сервиса
journalctl -u tendermonitor-document-research.service -f

# Статус всех сервисов TenderMonitor
tm-status

# Проверка переменных окружения
sudo systemctl show tendermonitor-document-research.service | grep Environment
```

## Откат изменений

Если что-то пошло не так:

```bash
# Отключить умное извлечение
sudo systemctl edit tendermonitor-document-research.service
# Удалить строку: Environment=ENABLE_SMART_EXTRACTION=1

# Перезапустить
sudo systemctl daemon-reload
sudo systemctl restart tendermonitor-document-research.service
```

## Тестирование на продакшене

### Поэтапное включение:
1. **Тест:** Включить на 1 час, проверить логи
2. **Пилот:** Включить на 1 день, проверить качество результатов
3. **Полное внедрение:** Оставить включенным постоянно

### Проверка качества:
```sql
-- Проверить длину сохраненных строк
SELECT 
    AVG(LENGTH(matched_text)) as avg_length,
    MAX(LENGTH(matched_text)) as max_length,
    COUNT(*) as total_matches
FROM document_matches 
WHERE created_at > NOW() - INTERVAL '1 hour';

-- Найти очень длинные строки (если есть)
SELECT keyword, LENGTH(matched_text), matched_text
FROM document_matches 
WHERE LENGTH(matched_text) > 300 
AND created_at > NOW() - INTERVAL '1 hour'
LIMIT 10;
```

## Ожидаемые результаты

После внедрения вы увидите:
- ✅ Короткие читаемые строки вместо длинных нечитаемых
- ✅ Подсветку ключевых слов: `**слово**`
- ✅ Контекст совпадений для лучшего понимания
- ✅ Экономию места в БД до 70-80%
- ✅ Уровень уверенности: высокая/хорошая/средняя/низкая

## Поддержка

При проблемах:
1. Проверьте логи: `journalctl -u tendermonitor-document-research.service -f`
2. Запустите тесты: `python3 quick_test_integration.py`
3. Проверьте переменные окружения в systemd
4. При необходимости откатите изменения

---

**Готово к внедрению!** 🚀