"""
Настройка логирования для проекта.
Логи выводятся в консоль (stdout) и в файлы.
"""
import os
import sys
from pathlib import Path
from loguru import logger

logger.remove()

_LOG_DIR = Path(os.getenv("TENDERMONITOR_LOG_DIR", ".")).resolve()
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.add(
    sys.stdout,
    level="INFO",
    colorize=False,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
)

logger.add(
    str(_LOG_DIR / "errors.log"),
    level="ERROR",
    rotation="1 week",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    backtrace=True,
    diagnose=True,
)

logger.add(
    str(_LOG_DIR / "debug.log"),
    level="DEBUG",
    rotation="1 day",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    retention="7 days",
)


def get_logger():
    """Возвращает настроенный logger."""
    return logger
