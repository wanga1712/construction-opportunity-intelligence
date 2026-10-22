# WIP PIPELINE_BATCH_PARALLEL_EXECUTION_V1 — батчи и параллельность

Status: DONE (2026-10-21). Owner: pipeline execution.

## Цель

Не гонять AI 24/7 и не ждать, пока весь корпус разберётся. Работать батчами с
явными лимитами на каждом этапе.

## Этапы и ресурсы

| Этап | Ресурсы | Параллельность |
|---|---|---|
| Admission / категория / preliminary medal | CPU+DB, лёгкий | батч до 200–500 |
| Download документов | сеть/диск, мало CPU | 2–4 воркера, EIS gate |
| Parse / OCR | CPU (tesseract), GPU не нужен | 2–4 OCR |
| Model / validator | GPU+CPU | только после parse, батч 50 |
| confirmed_base write | DB | после модели |

## Предлагаемый цикл

```text
03:00 sync S7 -> S13
03:15 admission/categories/preliminary medals, батч 500

далее днём:
  document pipeline батчами по 50 procurements:
    download -> parse/OCR -> structured_entities

  model validation отдельным окном:
    батч 50 candidate opportunities
    runtime cap 2–4 часа
```

Пока одна партия парсится, другая скачивается. Модель не блокирует
download/parse, но имеет низкий CPUWeight.

## Backpressure

```text
model стартует только если parsed candidates >= 50;
document workers стартуют всегда при наличии PENDING;
если CPU/GPU перегружены, снижаем OCR concurrency.
```

## Реализовано

- document batch `50` распределён по worker allocations:
  `open=10`, остальные восемь workers по `5`;
- effective process env проверен через `/proc/<pid>/environ`;
- download ограничен глобальным `DownloadCoordinator`:
  `MAX_ACTIVE_DOWNLOADS=4`;
- parse/OCR ограничен cross-process semaphore:
  normal `OCR_MAX_CONCURRENCY=4`;
- CPU backpressure снижает OCR до `2`, если load/cpu >= `0.9`;
- model batch `50`; AI запускается только при
  `parsed_candidates >= 50`;
- model gate на текущем pool: `parsed_candidates=880`, `PASS`;
- validator batch `50`, но service остаётся disabled/inactive;
- continuous second-pass worker переведён в manual oneshot
  `--once --limit 50` и disabled;
- GPU idle model выгружена; compute apps отсутствуют;
- AI timer остаётся daily, next run `2026-10-22 03:30 MSK`.

Проверки:

```text
DOCUMENT_BATCH_ALLOCATION=10+8*5=50
DOWNLOAD_PARALLEL_LIMIT=4
OCR_NORMAL=4
OCR_HIGH_LOAD=2
MODEL_BATCH=50
MODEL_GATE parsed_candidates=880 minimum=50 PASS
VALIDATOR_BATCH=50
AI_RUNNER=inactive/disabled
VALIDATOR=inactive/disabled
SECOND_PASS=inactive/disabled oneshot50
AI_TIMER=active
GPU_COMPUTE_APPS=none
```

## Acceptance

```text
PIPELINE_STAGES_ISOLATED=YES
DOWNLOAD_PARSE_PARALLEL=YES
MODEL_BATCH=50
DOCUMENT_BATCH=50
GPU_NOT_USED_FOR_DOCUMENT_PARSING=YES
AI_RUNS_IN_WINDOW_NOT_CONTINUOUS=YES
DB_WRITES=APPROVED_ONLY
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Deploy

```text
scripts/run_model_batch_with_gate.py
tender_documents_research/document_processor/ocr_concurrency.py
tender_documents_research/document_processor/context_validator_service.py
deploy/systemd/*-batch-policy.conf
deploy/systemd/*/60-pipeline-batch.conf
```

## Out of scope

- scoring/medal thresholds;
- queue admission policy;
- S7 parser.
