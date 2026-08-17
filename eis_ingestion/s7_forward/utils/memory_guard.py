"""
Утилиты для контроля потребления памяти процессом TenderMonitor.

Основная задача: при превышении заданного порога (например, 4 ГБ)
аккуратно завершить программу, чтобы внешний менеджер (systemd)
смог её перезапустить с "чистой" памятью.
"""

from __future__ import annotations

import sys
import time
from typing import Optional

MEMORY_LIMIT_MB = 4000  # Жёсткий порог в мегабайтах (4 ГБ)


def get_rss_mb() -> int:
    """
    Возвращает текущий объём используемой памяти (Resident Set Size)
    для текущего процесса в мегабайтах.

    Читает /proc/self/status и парсит строку VmRSS.
    В случае ошибки возвращает 0.
    """
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # Формат: VmRSS:   4607864 kB
                    kb_value = int(parts[1])
                    return kb_value // 1024
    except Exception:
        return 0

    return 0


def check_memory_and_exit_if_needed(
    logger,
    limit_mb: int = MEMORY_LIMIT_MB,
    grace_sleep_seconds: int = 5,
    context: Optional[str] = None,
) -> None:
    """
    Проверяет использование памяти и при превышении лимита
    мягко завершает процесс.

    :param logger: logger из utils.logger_config.get_logger
    :param limit_mb: Лимит памяти в мегабайтах (по умолчанию 4 ГБ)
    :param grace_sleep_seconds: Пауза перед завершением, чтобы дать
        завершиться фоновой активности (логирование, закрытие соединений)
    :param context: Дополнительный контекст (например, "после обработки даты 2025-12-15")
    """
    current_mb = get_rss_mb()
    if current_mb <= 0:
        return

    if current_mb <= limit_mb:
        return

    context_suffix = f" ({context})" if context else ""
    message = (
        f"Использование памяти превысило лимит{context_suffix}: "
        f"{current_mb} MB > {limit_mb} MB. "
        "Процесс будет мягко завершён для последующего перезапуска."
    )

    # Логируем как критическую ситуацию
    try:
        logger.critical(message)
    except Exception:
        # На всякий случай, если logger недоступен
        pass

    # Дублируем в stdout, чтобы было видно в журнале systemd
    print("\n⚠️  " + message)
    print(f"   Пауза {grace_sleep_seconds} сек перед завершением, чтобы завершить операции БД и логирование...")

    # Небольшая пауза, чтобы дать транзакциям/логам доработать
    time.sleep(grace_sleep_seconds)

    # Код выхода 3 — "контролируемый выход по лимиту памяти"
    sys.exit(3)

import time
from typing import Optional

from utils.logger_config import get_logger


MEMORY_LIMIT_MB = 4000  # Жёсткий порог: 4 ГБ


def get_rss_mb() -> int:
    """
    Возвращает текущее использование памяти процессом (Resident Set Size) в мегабайтах.

    Читает значение из /proc/self/status (Linux).
    При ошибке возвращает 0, чтобы не ломать основную логику.
    """
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # Пример строки: "VmRSS:   4607864 kB"
                    kb_value = int(parts[1])
                    return kb_value // 1024
    except Exception:
        return 0

    return 0


def check_memory_and_maybe_exit(
    logger=None,
    pause_before_exit_sec: int = 10,
) -> None:
    """
    Проверяет использование памяти процесса и мягко завершает программу,
    если порог превышен.

    Логика:
    - если RSS > MEMORY_LIMIT_MB, логируем предупреждение,
      даём небольшой "grace period" (по умолчанию 10 секунд)
      и выходим с кодом 1. Ожидается, что systemd перезапустит сервис.

    Функция вызывается после завершения обработки "батча" данных
    (например, после обработки одной даты), чтобы все транзакции БД
    уже были закоммичены.
    """
    if logger is None:
        logger = get_logger()

    rss_mb = get_rss_mb()
    if not rss_mb:
        return

    if rss_mb <= MEMORY_LIMIT_MB:
        return

    warning_message = (
        f"Использование памяти превысило лимит: {rss_mb} MB > {MEMORY_LIMIT_MB} MB. "
        f"Мягкое завершение процесса для перезапуска."
    )
    logger.error(warning_message)

    print("\n" + "=" * 60)
    print("⚠️  КРИТИЧЕСКОЕ ИСПОЛЬЗОВАНИЕ ПАМЯТИ")
    print("=" * 60)
    print(f"Текущая память процесса: {rss_mb} MB")
    print(f"Лимит: {MEMORY_LIMIT_MB} MB")
    print(
        f"Программа будет мягко завершена через {pause_before_exit_sec} секунд "
        f"для предотвращения утечек. Ожидается автоматический перезапуск сервисом."
    )
    print("=" * 60 + "\n")

    if pause_before_exit_sec > 0:
        time.sleep(pause_before_exit_sec)

    # Завершение процесса. Авто‑рестарт обрабатывается systemd (Restart=always)
    raise SystemExit(1)

