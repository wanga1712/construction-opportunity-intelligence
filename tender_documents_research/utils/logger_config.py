"""
Настройка логирования для проекта.
Логи выводятся в консоль (stdout) и в файлы.
"""
import sys
from loguru import logger

# Удаляем стандартный обработчик loguru
logger.remove()

# Вывод в консоль (stdout) — INFO и выше, для мониторинга
logger.add(
    sys.stdout,
    level="INFO",
    colorize=False,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
)

# Вывод ошибок в файл с полным трейсбеком
logger.add(
    "errors.log",
    level="ERROR",
    rotation="1 week",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    backtrace=True,
    diagnose=True,
)

# Подробные DEBUG-логи в файл (все уровни)
logger.add(
    "debug.log",
    level="DEBUG",
    rotation="1 day",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    retention="7 days",
)


def get_logger():
    """Возвращает настроенный logger."""
    return logger
