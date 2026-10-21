# WIP RESOURCE_PRIORITY_DOC_PIPELINE_FIRST_V1 — документы в приоритете

Status: DONE (2026-10-21). Owner: systemd / infrastructure.

## Проблема

Сервер занят AI/validator/OCR backlog, а документный конвейер голодает:
сегодня завершено только 3 закупки.

## Приоритеты

1. Новые закупки → документный конвейер.
2. Model/validator — только после документов и по мере свободных ресурсов.
3. OCR — ограниченный параллелизм.

## Ресурсная модель

```text
document daemons:
  CPUWeight 400–500
  Nice -5..0
  CPUQuota не ограничивать

OCR:
  max 2–4 параллельных процесса

AI runner / validator:
  CPUWeight 10–20
  Nice 10
  GPU только по требованию, не background drain

Ollama/llama-server:
  не использовать для парсинга документов
```

## Изменения

1. Остановить/перевести в ручной режим:
   - `crm-ai-assessment-runner`
   - `crm-v3-context-validator`
2. Поднять приоритет document daemons.
3. Ограничить OCR concurrency.
4. GPU оставить для ручного/пакетного model inference, а не постоянного drain.

## Timer / schedule

Сейчас `crm-ai-assessment-runner.timer` запускает oneshot каждые 45 секунд:

```text
OnUnitActiveSec=45s
```

Это и есть причина, почему AI-модель молотит целый день. Нужно:

```text
запускать runner после дневного sync/new arrivals;
либо OnCalendar=daily;
либо ручной trigger после run_crm_sync;
Persistent=false.
```

## Реализовано

- все девять активных document workers (`daemon-open/-2/-3`,
  `daemon-awarded`, пять band workers) переведены на
  `CPUWeight=450`, `Nice=-5`;
- старые `CPUQuota` у `open-3` и `band-wood` сняты:
  effective `CPUQuotaPerSecUSec=infinity`;
- добавлен cross-process OCR semaphore
  `document_processor/ocr_concurrency.py`;
- semaphore применён в `parse_utils.py` (rotation probe и page OCR) и
  `pdf_processor.py`;
- `OCR_MAX_CONCURRENCY=4`, вычислительные библиотеки ограничены одним
  потоком (`OMP/OPENBLAS/MKL/NUMEXPR`);
- AI runner/validator и активные model workers получили
  `CPUWeight=15`, `Nice=10`;
- AI runner и validator остаются `inactive/disabled`; AI timer остаётся
  `active/enabled`, next run `2026-10-22 03:30 MSK`;
- document parsing использует только CPU/tesseract;
  CUDA/TensorRT в parser-path отсутствуют.

Проверки:

```text
DOCUMENT_WORKERS_ACTIVE=9/9
DOCUMENT_CPUWEIGHT=450
DOCUMENT_NICE=-5
DOCUMENT_CPUQUOTA=infinity
OCR_SEMAPHORE_SYNTHETIC=8 processes -> max 4, failures 0
OCR_LIVE_TESSERACT_PROCESSES=4
AI_RUNNER=inactive
VALIDATOR=inactive/disabled
AI_RUNNER_TIMER=active
AI_RUNNER_CPUWEIGHT=15
AI_RUNNER_NICE=10
VALIDATOR_CPUWEIGHT=15
VALIDATOR_NICE=10
GPU_PARSER_DEPENDENCY=NONE
```

Короткий live-warmup:

```text
COMPLETED_PROCUREMENTS_BEFORE: 2 / 60m
COMPLETED_PROCUREMENTS_AFTER: 6 / 10m
QUEUE_WAITING=452
QUEUE_WORKING=26
```

Рост зафиксирован на коротком окне прогрева; устойчивый throughput
остаётся предметом следующего canary, без изменения scoring/queue
semantics.

Acceptance:

```text
AI_VALIDATOR_BACKGROUND_DRAIN_STOPPED=YES
DOCUMENT_DAEMONS_HIGHER_PRIORITY=YES
OCR_CONCURRENCY_BOUNDED=YES
GPU_NOT_USED_FOR_DOCUMENT_PARSING=YES
COMPLETED_PROCUREMENTS_PER_HOUR_INCREASED=WARMUP_YES (2/60m -> 6/10m)
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Deploy

```text
deploy/systemd/*.service.d/50-document-priority.conf
deploy/systemd/*.service.d/25-low-resource-priority.conf
tender_documents_research/document_processor/ocr_concurrency.py
tender_documents_research/document_processor/parse_utils.py
tender_documents_research/document_processor/pdf_processor.py
```

Backups:

```text
/tmp/parse_utils.py.bak-p13-20261021
/tmp/pdf_processor.py.bak-p13-20261021
```

## Out of scope

- scoring/medal;
- queue admission;
- model quality.
