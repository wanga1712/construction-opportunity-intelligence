"""
Оркестратор основного цикла TenderMonitor.

Задачи:
- управлять датами обработки (от начальной до текущей и далее в режиме мониторинга);
- координировать запросы к ЕИС и обработку регионов;
- сохранять и восстанавливать прогресс по регионам и датам;
- взаимодействовать с измерением статистики и контролем памяти.

ВНИМАНИЕ:
- В этом модуле нет ОС-специфичной логики (никакого /proc, systemd и т.п.);
- Вся работа с окружением и запуском сервиса остаётся в main.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Set, Dict, Any


@dataclass
class MonitoringConfig:
    """Конфигурация цикла мониторинга и обработки дат."""

    start_date: datetime
    today: datetime
    monitoring_interval_seconds: int
    eis_data_upload_hour: int
    direction: str = "forward"  # forward | backward
    stop_before_date: datetime | None = None  # for backward: stop when date < this


class TenderMonitorService:
    """
    Класс-оркестратор, инкапсулирующий основной цикл обработки дат.

    Отвечает только за доменную и оркестрационную логику:
    - выбор дат;
    - запуск мониторинга появления данных в ЕИС;
    - вызов обработчиков даты и сохранение прогресса.

    Взаимодействие с:
    - логгером (loguru) через переданный экземпляр;
    - EISRequester через переданные фабрики/коллбеки;
    - БД и файловой системой — только через переданные функции.
    """

    def __init__(
        self,
        config: MonitoringConfig,
        logger,
        *,
        check_data_available: Callable[[str], bool],
        monitor_for_new_data: Callable[[datetime], bool],
        get_processed_regions_for_date: Callable[[str], Set[int]],
        mark_region_processed: Callable[[str, int], None],
        clear_region_progress_for_date: Callable[[str], None],
        update_config_date: Callable[[datetime], None],
        get_stats_snapshot: Callable[[], Dict[str, int]],
        create_eis_requester: Callable[[str], Any],
        on_memory_check: Callable[[str], None],
    ) -> None:
        """
        Инициализация сервиса TenderMonitor.

        Все внешние зависимости передаются через параметры конструктора,
        чтобы не смешивать слои и упростить тестирование.
        """
        self._cfg = config
        self._logger = logger
        self._check_data_available = check_data_available
        self._monitor_for_new_data = monitor_for_new_data
        self._get_processed_regions_for_date = get_processed_regions_for_date
        self._mark_region_processed = mark_region_processed
        self._clear_region_progress_for_date = clear_region_progress_for_date
        self._update_config_date = update_config_date
        self._get_stats_snapshot = get_stats_snapshot
        self._create_eis_requester = create_eis_requester
        self._on_memory_check = on_memory_check

    def run(self) -> None:
        """
        Запускает основной бесконечный цикл обработки дат и мониторинга.

        ВНИМАНИЕ:
        - Ожидается, что все критические ошибки БД будут обрабатываться
          на уровне вызывающего кода (main.py) через обёртки/try-except.
        """
        processed_count = 0
        error_count = 0

        initial_date = self._cfg.start_date
        today = self._cfg.today
        direction = (self._cfg.direction or "forward").lower()
        stop_before = self._cfg.stop_before_date

        if direction == "backward":
            if stop_before is None:
                print("⚠️  backward: не задан stop_before_date")
                return
            total_days = (initial_date - stop_before).days
            if total_days <= 0:
                print(
                    f"⚠️  backward: старт {initial_date.strftime('%Y-%m-%d')} "
                    f"не позже стопа {stop_before.strftime('%Y-%m-%d')}"
                )
                return
            print(f"\n📅 ПЛАН ОБРАБОТКИ (BACKWARD):")
            print(f"   Начальная дата: {initial_date.strftime('%Y-%m-%d')}")
            print(f"   Стоп (не включая): {stop_before.strftime('%Y-%m-%d')}")
            print(f"   Всего дней для обработки: {total_days}")
            print("   ℹ️  Основной демон владеет сегодня/вчера — этот контур их не трогает")
        else:
            total_days = (today - initial_date).days + 1
            if total_days <= 0:
                print(
                    f"⚠️  Внимание: начальная дата ({initial_date.strftime('%Y-%m-%d')}) "
                    f"больше или равна текущей дате ({today.strftime('%Y-%m-%d')})"
                )
                return
            print(f"\n📅 ПЛАН ОБРАБОТКИ:")
            print(f"   Начальная дата: {initial_date.strftime('%Y-%m-%d')}")
            print(f"   Конечная дата (сегодня): {today.strftime('%Y-%m-%d')}")
            print(f"   Всего дней для обработки: {total_days}")
        print(
            "   ℹ️  Файлы проверяются в БД - уже обработанные файлы будут автоматически пропущены"
        )
        print(
            "   ℹ️  Прогресс обработки регионов кешируется - при перезапуске будет продолжение"
        )
        print(f"\n{'=' * 60}\n")

        date_to_process = initial_date
        current_day = 0
        monitoring_mode = False

        while True:
            if direction == "backward":
                if date_to_process < stop_before:
                    print(f"\n✅ BACKWARD: достигнута граница {stop_before.strftime('%Y-%m-%d')}, выход")
                    self._logger.info(
                        f"Backward catchup finished at boundary {stop_before.strftime('%Y-%m-%d')}"
                    )
                    return
            else:
                # Проверяем, достигли ли мы вчерашней даты (today - 1)
                yesterday = datetime.today() - timedelta(days=1)
                if date_to_process >= today:
                    if not monitoring_mode:
                        monitoring_mode = True
                        date_to_process = yesterday
                        print(f"\n{'=' * 60}")
                        print(f"📅 ДОСТИГНУТА ВЧЕРАШНЯЯ ДАТА: {yesterday.strftime('%Y-%m-%d')}")
                        print(f"{'=' * 60}")
                        print("🔄 Переход в режим непрерывного мониторинга...")
                        print(f"ℹ️  Программа будет ждать появления данных за {yesterday.strftime('%Y-%m-%d')}")
                        self._logger.info(f"Достигнута вчерашняя дата {yesterday.strftime('%Y-%m-%d')}, переход в режим мониторинга")

            current_day += 1
            date_str = date_to_process.strftime("%Y-%m-%d")

            # В режиме мониторинга для вчерашней даты сначала проверяем наличие данных
            # (только forward; backward — догоняющий catchup без ожидания ЕИС)
            if monitoring_mode and direction != "backward":
                if not self._check_data_available(date_str):
                    self._monitor_for_new_data(date_to_process)
                    continue

            print(f"\n{'=' * 60}")
            if monitoring_mode:
                print(f"📅 [МОНИТОРИНГ] ОБРАБОТКА ДАТЫ: {date_str}")
            else:
                print(f"📅 [{current_day}/{total_days}] ОБРАБОТКА ДАТЫ: {date_str}")
            print(f"{'=' * 60}")
            self._logger.info(f"Начало обработки даты {date_str}")

            # Обновляем дату в конфиге только для текущей обработки
            self._update_config_date(date_to_process)
            self._logger.info(f"Дата в config.ini обновлена на {date_str} для обработки")

            # Загружаем прогресс обработки регионов
            processed_regions = self._get_processed_regions_for_date(date_str)
            if processed_regions:
                self._logger.info(
                    f"Найдено уже обработанных регионов для даты {date_str}: {len(processed_regions)}"
                )

            try:
                # Снимок статистики до обработки
                stats_before = self._get_stats_snapshot()

                # Создаём EISRequester на конкретную дату
                eis_requester = self._create_eis_requester(date_str)

                # Callback для сохранения прогресса
                def on_region_processed(region_code: int) -> None:
                    self._mark_region_processed(date_str, region_code)
                    self._logger.debug(
                        f"Прогресс сохранен: регион {region_code} для даты {date_str}"
                    )

                # Обрабатываем запросы с учётом уже обработанных регионов
                eis_requester.process_requests(
                    processed_regions=processed_regions,
                    on_region_processed=on_region_processed,
                )

                # Снимок статистики после обработки
                stats_after = self._get_stats_snapshot()

                date_stats: Dict[str, int] = {}
                skipped_stats: Dict[str, int] = {}

                all_keys = set(stats_before.keys()) | set(stats_after.keys())
                for key in all_keys:
                    before_value = stats_before.get(key, 0)
                    after_value = stats_after.get(key, 0)
                    delta = after_value - before_value
                    if delta > 0:
                        if "_skipped" in key:
                            skipped_stats[key] = delta
                        else:
                            date_stats[key] = delta

                processed_count += 1

                # Очищаем прогресс регионов после успешной обработки
                self._clear_region_progress_for_date(date_str)
                self._logger.info(
                    f"Прогресс обработки регионов для даты {date_str} очищен"
                )

                # Выводим краткую статистику
                self._print_date_stats(date_str, processed_count, total_days, date_stats, skipped_stats)
                self._logger.info(f"Дата {date_str} успешно обработана")

            except Exception:
                # Ошибки внутри обработки даты логируются на верхнем уровне main.py,
                # здесь считаем только факт ошибки.
                error_count += 1
                raise
            finally:
                # Перед переходом к следующей дате вызываем внешний контроль памяти
                safe_context = f"после обработки даты {date_str}"
                self._on_memory_check(safe_context)

            # Переход к следующей дате
            if direction == "backward":
                date_to_process -= timedelta(days=1)
                print(
                    f"📅 BACKWARD: переход к {date_to_process.strftime('%Y-%m-%d')}"
                )
                self._logger.info(
                    f"Backward next date: {date_to_process.strftime('%Y-%m-%d')}"
                )
            elif not monitoring_mode:
                date_to_process += timedelta(days=1)
            else:
                # В режиме мониторинга всегда переходим к следующему дню после обработки
                date_to_process += timedelta(days=1)
                next_date_str = date_to_process.strftime('%Y-%m-%d')
                print(
                    f"📅 Переход к следующей дате для мониторинга: {next_date_str}"
                )
                self._logger.info(f"Переход к следующей дате: {next_date_str}")

    def _print_date_stats(
        self,
        date_str: str,
        processed_count: int,
        total_days: int,
        date_stats: Dict[str, int],
        skipped_stats: Dict[str, int],
    ) -> None:
        """Выводит человекочитаемую статистику по одной дате."""
        print(f"\n{'=' * 60}")
        print(
            f"✅ Дата {date_str} успешно обработана "
            f"({processed_count} из {total_days})"
        )
        print(f"{'=' * 60}")

        print(f"📊 СТАТИСТИКА ПО ДАТЕ {date_str}:")

        customers_added = date_stats.get("customer", 0)
        customers_skipped_dup = skipped_stats.get("customer_skipped_duplicate", 0)
        customers_skipped_contact = skipped_stats.get("customer_skipped_contact", 0)
        customers_total_skipped = customers_skipped_dup + customers_skipped_contact

        contractors_added = date_stats.get("contractor", 0)
        contractors_skipped_dup = skipped_stats.get("contractor_skipped_duplicate", 0)
        contractors_skipped_contact = skipped_stats.get("contractor_skipped_contact", 0)
        contractors_total_skipped = (
            contractors_skipped_dup + contractors_skipped_contact
        )

        contracts_44_added = date_stats.get("reestr_contract_44_fz", 0)
        contracts_223_added = date_stats.get("reestr_contract_223_fz", 0)
        contracts_total = contracts_44_added + contracts_223_added

        print(
            "   👥 Заказчики: добавлено "
            f"{customers_added}, пропущено {customers_total_skipped} "
            f"(дубликаты: {customers_skipped_dup}, существующий контакт: {customers_skipped_contact})"
        )
        print(
            "   🏢 Подрядчики: добавлено "
            f"{contractors_added}, пропущено {contractors_total_skipped} "
            f"(дубликаты: {contractors_skipped_dup}, существующий контакт: {contractors_skipped_contact})"
        )
        print(
            "   📋 Контракты: добавлено "
            f"{contracts_total} (44-ФЗ: {contracts_44_added}, 223-ФЗ: {contracts_223_added})"
        )

        other_stats: Dict[str, int] = {}
        for key, value in date_stats.items():
            if key not in [
                "customer",
                "contractor",
                "reestr_contract_44_fz",
                "reestr_contract_223_fz",
            ]:
                other_stats[key] = value

        if other_stats:
            print("   📦 Прочее:")
            ru_labels = {
                "links_documentation_44_fz": "Ссылок 44-ФЗ",
                "links_documentation_223_fz": "Ссылок 223-ФЗ",
                "trading_platform": "Торговых площадок",
                "file_names_xml": "Файлов XML",
            }
            for key, value in other_stats.items():
                label = ru_labels.get(key, key)
                print(f"      • {label}: {value}")

        files_skipped_processed = skipped_stats.get(
            "files_skipped_already_processed", 0
        )
        files_skipped_no_okpd = skipped_stats.get("files_skipped_no_okpd", 0)
        files_total_skipped = files_skipped_processed + files_skipped_no_okpd

        if files_total_skipped > 0:
            print(
                "   📄 Файлы пропущены: "
                f"{files_total_skipped} (уже обработаны: {files_skipped_processed}, нет ОКПД: {files_skipped_no_okpd})"
            )


