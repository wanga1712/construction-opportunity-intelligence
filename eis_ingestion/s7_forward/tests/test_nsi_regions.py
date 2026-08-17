"""
Тестовый скрипт для получения кодов регионов через НСИ ЕИС (nsiOpenDataList).

Запускается отдельно от основного сервиса, использует тот же токен и прокси.

Пример запуска на сервере:

    cd /opt/tendermonitor
    source venv/bin/activate
    python tests/test_nsi_regions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень проекта (/opt/tendermonitor) в sys.path,
# чтобы импорт nsi_client работал при запуске из папки tests.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nsi_client import EisNsiClient
from utils.logger_config import get_logger


logger = get_logger()


def main() -> None:
    client = EisNsiClient()

    print("\n============================================================")
    print("ТЕСТ НСИ: nsiOpenDataList (коды регионов)")
    print("============================================================")

    try:
        regions = client.get_region_codes_from_open_data()
    except Exception as e:
        print(f"❌ Ошибка при получении регионов через НСИ: {e}")
        logger.error(f"Ошибка при получении регионов через НСИ: {e}", exc_info=True)
        return

    if not regions:
        print("⚠️  Справочник nsiOpenDataList вернулся без regionCode")
        return

    print(f"✅ Уникальных регионов (regionCode): {len(regions)}")
    print("------------------------------------------------------------")
    print(", ".join(regions))
    print("------------------------------------------------------------")


if __name__ == "__main__":
    main()

