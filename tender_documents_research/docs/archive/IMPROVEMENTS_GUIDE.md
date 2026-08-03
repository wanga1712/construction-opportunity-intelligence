# Руководство по внедрению улучшений TenderMonitor

## 📋 Краткое резюме

Система fuzzy поиска уже работает отлично (**8.5/10**). Созданные улучшения добавляют полезные возможности, но не критичны для текущей работы.

## ✅ Что уже исправлено

1. **Stunnel восстановлен** — исправлена конфигурация `eis-stunnel.service`, порт 8080 работает
2. **Мониторинг настроен** — автоматическая проверка каждые 5 минут, команды `tm-status`
3. **Документация обновлена** — README дополнен информацией о fuzzy поиске и мониторинге

## 🚀 Поэтапное внедрение улучшений

### Этап 1: Немедленные улучшения (низкий риск)

**1.1. Установить pymorphy2 для морфологического анализа:**
```bash
cd /opt/tender_documents_research
.venv/bin/pip install pymorphy2
```

**1.2. Создать индексы в БД для ускорения загрузки ключевых слов:**
```sql
-- Подключиться к БД product_catalog_2
CREATE INDEX IF NOT EXISTS idx_products_name_lower ON products (LOWER(name));
CREATE INDEX IF NOT EXISTS idx_products_name_length ON products (LENGTH(name)) WHERE LENGTH(name) >= 3;
```

**1.3. Добавить переменные окружения в systemd сервис:**
```bash
sudo systemctl edit tendermonitor-document-research.service
```
Добавить:
```ini
[Service]
Environment=MATCHER_CACHE_TTL=3600
Environment=MATCHER_USE_MORPH=true
Environment=MATCHER_LOG_LEVEL=INFO
```

**1.4. Перезапустить сервис:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart tendermonitor-document-research.service
```

### Этап 2: Тестирование улучшенного matcher (средний риск)

**2.1. Запустить бенчмарк для сравнения:**
```bash
cd /opt/tender_documents_research
python3 benchmark_matcher.py
```

**2.2. Запустить тесты:**
```bash
python3 tests/test_matcher_extended.py
```

**2.3. Если результаты удовлетворительные, можно заменить оригинальный matcher:**
```bash
# Создать резервную копию
cp document_processor/matcher.py document_processor/matcher_original.py

# Заменить на улучшенную версию (ОСТОРОЖНО!)
# Это требует тщательного тестирования
```

### Этап 3: Дополнительные настройки (по желанию)

**3.1. Настроить индивидуальные пороги для специфических ключевых слов:**
```bash
cat > keyword_thresholds.json << 'EOF'
{
  "бм 0332": 100,
  "бм 0333": 100,
  "пу 500": 85,
  "эп 200": 85,
  "рм3": 90
}
EOF
```

**3.2. Добавить пользовательские ключевые слова:**
```bash
cat > user_keywords.json << 'EOF'
[
  "композитные перильные ограждения",
  "стеклопластиковые перильные ограждения", 
  "стеклопластиковые перила",
  "композитные водоотводные лотки",
  "стеклопластиковые водоотводные лотки",
  "усиление конструкций"
]
EOF
```

## 📊 Мониторинг результатов

**Проверка статуса системы:**
```bash
tm-status
```

**Просмотр логов:**
```bash
journalctl -u tendermonitor-document-research.service -f
```

**Мониторинг производительности:**
```bash
tm-monitor-logs --tail
```

## ⚠️ Важные предупреждения

1. **Не заменяйте оригинальный matcher без тщательного тестирования**
2. **Создавайте резервные копии перед изменениями**
3. **Тестируйте на небольшом объеме данных сначала**
4. **Мониторьте производительность после изменений**

## 🔧 Откат изменений

Если что-то пошло не так:

```bash
# Откатить matcher
cp document_processor/matcher_original.py document_processor/matcher.py

# Убрать переменные окружения
sudo systemctl revert tendermonitor-document-research.service

# Перезапустить сервис
sudo systemctl daemon-reload
sudo systemctl restart tendermonitor-document-research.service
```

## 📈 Ожидаемые результаты

**После внедрения Этапа 1:**
- Улучшение работы с русским склонением (композитные → композитных)
- Ускорение загрузки ключевых слов из БД
- Более детальное логирование

**После внедрения Этапа 2:**
- Возможное ускорение обработки (зависит от размера документов)
- Более точные совпадения благодаря адаптивным порогам
- Детальная статистика производительности

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи: `journalctl -u tendermonitor-document-research.service -n 50`
2. Проверьте статус: `tm-status`
3. Запустите тесты: `python3 tests/test_matcher_extended.py`
4. При необходимости откатите изменения (см. выше)

---

**Итог:** Система уже работает отлично. Улучшения добавляют полезные возможности, но внедрять их следует постепенно и с осторожностью.