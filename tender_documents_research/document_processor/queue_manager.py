import os
from typing import List, Dict, Optional, Sequence

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger

from .queue_priority import QueuePriorityPolicy


# Терминальный статус для закупок вне 90-дневного продажного окна.
# Это НЕ ошибка обработки: документы не качаем и не парсим, потому что
# продавать материалы уже поздно ("не успели обработать до окончания").
STATUS_SALES_WINDOW_EXPIRED = "sales_window_expired"


class QueueManager:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()
        self.logger = get_logger()
        self.priority = QueuePriorityPolicy()
        self.allowed_table_sources = self._parse_table_sources_env()
        self.source_tables = self._filter_source_tables(self.priority.all_tables_ordered())
        self.populate_limit = int(os.getenv("QUEUE_POPULATE_LIMIT", "10"))
        self.sales_window_days = int(os.getenv("SALES_WINDOW_MIN_DAYS", "90"))
        # Для НОВЫХ (open): не ближе чем N дней до end_date, в очереди — самые ближайшие.
        try:
            self.open_min_days_to_end = max(0, int(os.getenv("OPEN_TENDERS_MIN_DAYS_TO_END", "3")))
        except ValueError:
            self.open_min_days_to_end = 3


    @staticmethod
    def _parse_table_sources_env():
        raw = (os.getenv("QUEUE_TABLE_SOURCES") or "").strip()
        if not raw:
            return None
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts or None

    def _filter_source_tables(self, tables):
        if not self.allowed_table_sources:
            return list(tables)
        allowed = set(self.allowed_table_sources)
        filtered = [t for t in tables if t in allowed]
        if not filtered:
            raise ValueError(
                "QUEUE_TABLE_SOURCES=%r не пересекается с известными таблицами: %r"
                % (self.allowed_table_sources, list(tables))
            )
        return filtered

    def _claim_table_filter_sql(self):
        if not self.allowed_table_sources:
            return "", []
        placeholders = ", ".join(["%s"] * len(self.allowed_table_sources))
        return " AND table_source IN (%s)" % placeholders, list(self.allowed_table_sources)

    def handles_high_priority(self):
        if not self.allowed_table_sources:
            return True
        allowed = set(self.allowed_table_sources)
        return any(t in allowed for t in self.priority.high_tables())

    def soft_reclassify_pending(self) -> int:
        """
        Мягко перескладывает pending-задачи между open/awarded,
        если на 7-м изменилась стадия закупки.
        """
        rules = [
            (
                "reestr_contract_44_fz",
                "reestr_contract_44_fz_awarded",
                "reestr_contract_44_fz_awarded",
            ),
            (
                "reestr_contract_223_fz",
                "reestr_contract_223_fz_awarded",
                "reestr_contract_223_fz_awarded",
            ),
            (
                "reestr_contract_44_fz_awarded",
                "reestr_contract_44_fz",
                "reestr_contract_44_fz",
            ),
            (
                "reestr_contract_223_fz_awarded",
                "reestr_contract_223_fz",
                "reestr_contract_223_fz",
            ),
        ]
        total = 0
        for src_table, dst_table, probe_table in rules:
            sql = f"""
                UPDATE document_processing_queue q
                SET table_source = %s,
                    error_message = CONCAT('soft_reclassify:', COALESCE(q.error_message, ''))
                WHERE q.status = 'pending'
                  AND q.table_source = %s
                  AND EXISTS (
                    SELECT 1
                    FROM {probe_table} t
                    WHERE t.contract_number = q.contract_reg_number
                  )
                RETURNING q.id
            """
            rows = self.db.execute_query(sql, (dst_table, src_table), fetch=True) or []
            # execute_query для UPDATE может вернуть [] — считаем через rowcount fallback.
            try:
                changed = len(rows)
            except Exception:
                changed = 0
            total += changed
        if total:
            self.logger.info(f"[queue] soft_reclassify pending updated: {total}")
        return total

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _queue_fz_dedup_sql(contract_alias: str, table_source: str) -> str:
        """
        Исключает дубли: одна закупка (contract_number) — одна задача на контур ФЗ,
        независимо от table_source в очереди.
        """
        if "223" in table_source:
            fz_match = "q.table_source LIKE '%%223%%'"
        else:
            fz_match = "q.table_source LIKE '%%44%%'"
        return f"""
            AND NOT EXISTS (
                SELECT 1
                FROM document_processing_queue q
                WHERE q.contract_reg_number = {contract_alias}
                  AND {fz_match}
            )
        """

    def _is_open_registry(self, table: str) -> bool:
        """Новые (open) реестры — не awarded/completed/unclear/commission."""
        return self.priority.is_high_priority(table)

    def _populate_debug(self, table: str, limit_rows: int) -> int:
        params: List[object] = [table, table, limit_rows]
        end_date_filter = self._date_filter_sql(table, "t")
        order_sql = self._populate_order_sql(table, "t")
        sql = f"""
            WITH inserted AS (
                INSERT INTO document_processing_queue (contract_reg_number, table_source, status)
                SELECT t.contract_number, %s, 'pending'
                FROM {table} t
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM document_processing_queue q
                    WHERE q.contract_reg_number = t.contract_number
                      AND q.table_source = %s
                )
                {end_date_filter}
                {self._queue_fz_dedup_sql("t.contract_number", table)}
                ORDER BY {order_sql}
                ON CONFLICT (contract_reg_number) DO NOTHING
                LIMIT %s
                RETURNING id
            )
            SELECT COUNT(*) FROM inserted;
        """
        rows = self.db.execute_query(sql, tuple(params), fetch=True)
        count = rows[0][0] if rows else 0
        return count

    def _get_table_id_range(self, table: str):
        """Получает min/max id таблицы для батчевого обхода"""
        rows = self.db.execute_query(f"SELECT MIN(id), MAX(id) FROM {table}", fetch=True)
        if rows and rows[0][0] is not None:
            return rows[0][0], rows[0][1]
        return None, None

    def _date_filter_sql(self, table: str, alias: str = "t") -> str:
        """
        Open (новые): end_date >= today + OPEN_TENDERS_MIN_DAYS_TO_END (default 3).
        Awarded: продажное окно по COALESCE(delivery_end_date, end_date) >= today + 90d.
        """
        if self._is_open_registry(table):
            days = self.open_min_days_to_end
            return (
                f" AND {alias}.end_date IS NOT NULL"
                f" AND {alias}.end_date::date >= (CURRENT_DATE + INTERVAL '{days} days')"
            )
        days = self.sales_window_days
        return (
            f" AND COALESCE({alias}.delivery_end_date, {alias}.end_date) IS NOT NULL"
            f" AND COALESCE({alias}.delivery_end_date, {alias}.end_date)::date "
            f">= (CURRENT_DATE + INTERVAL '{days} days')"
        )

    def _populate_order_sql(self, table: str, alias: str = "t") -> str:
        """Open: ближайший end_date первым. Awarded: свежие по дате старта."""
        if self._is_open_registry(table):
            return f"{alias}.end_date ASC NULLS LAST, {alias}.id DESC"
        return f"COALESCE({alias}.start_date, {alias}.end_date) DESC NULLS LAST, {alias}.id DESC"

    def _date_filter_horizon_label(self, table: str) -> str:
        if self._is_open_registry(table):
            return f", open_end_date>=+{self.open_min_days_to_end}d nearest-first"
        return f", sales_window>={self.sales_window_days}d"

    # backward-compatible alias used by older tests
    def _new_tenders_end_date_filter(self, table: str, alias: str = "t") -> str:
        return self._date_filter_sql(table, alias)

    def purge_lost_sales_window(self) -> int:
        """Снимает pending вне окна: open — по end_date; awarded — по 90д продаже."""
        tables = [t for t in self.source_tables if t.startswith("reestr_contract_")]
        if not tables:
            return 0
        parts = []
        for table in tables:
            if self._is_open_registry(table):
                lost_pred = f"""
                    t.end_date IS NULL
                    OR t.end_date::date
                       < (CURRENT_DATE + INTERVAL '{self.open_min_days_to_end} days')
                """
            else:
                lost_pred = f"""
                    COALESCE(t.delivery_end_date, t.end_date) IS NULL
                    OR COALESCE(t.delivery_end_date, t.end_date)::date
                       < (CURRENT_DATE + INTERVAL '{self.sales_window_days} days')
                """
            parts.append(
                f"""
                SELECT q.id
                FROM document_processing_queue q
                JOIN {table} t ON t.contract_number = q.contract_reg_number
                WHERE q.status = 'pending'
                  AND q.table_source = '{table}'
                  AND ({lost_pred})
                """
            )
        sql = f"""
            WITH lost AS (
                {' UNION '.join(parts)}
            )
            UPDATE document_processing_queue q
            SET status = %s,
                completed_at = NOW(),
                error_message = %s
            FROM lost
            WHERE q.id = lost.id
            RETURNING q.id
        """
        rows = self.db.execute_query(
            sql,
            (
                STATUS_SALES_WINDOW_EXPIRED,
                (
                    f"window_expired: open<{self.open_min_days_to_end}d to end_date "
                    f"or awarded sales_window<{self.sales_window_days}d"
                ),
            ),
            fetch=True,
        ) or []
        count = len(rows)
        if count:
            self.logger.info(f"[queue] снято задач вне окна: {count}")
        return count

    def _okpd_join_sql(self) -> str:
        """
        ОКПД пользователя: все коды user_id (все категории: стройка/проектирование/компы).
        category_id в user_search_settings — UI-якорь, не ограничивает populate.
        """
        use_prefix = os.getenv("OKPD_MATCH_PREFIX") == "1"
        if use_prefix:
            return """JOIN okpd_from_users ofu ON ofu.user_id = uss.user_id
                    JOIN collection_codes_okpd cco ON cco.id = t.okpd_id
                                                  AND (cco.main_code LIKE ofu.okpd_code || '%%'
                                                       OR cco.sub_code LIKE ofu.okpd_code || '%%')"""
        return """JOIN okpd_from_users ofu ON ofu.user_id = uss.user_id
                    JOIN collection_codes_okpd cco ON cco.id = t.okpd_id
                                                  AND (cco.main_code = ofu.okpd_code
                                                       OR cco.sub_code = ofu.okpd_code)"""

    def _populate_with_filters(self, table: str, limit_rows: int) -> int:
        ignore_okpd = os.getenv("IGNORE_OKPD_FILTER") == "1"
        okpd_join = "" if ignore_okpd else self._okpd_join_sql()

        end_date_filter = self._date_filter_sql(table, "t")
        order_sql = self._populate_order_sql(table, "t")
        cand_ord_expr = (
            "t.end_date"
            if self._is_open_registry(table)
            else "COALESCE(t.start_date, t.end_date)"
        )
        horizon = self._date_filter_horizon_label(table)
        msg = f"[populate] {table}: ignore_okpd={ignore_okpd}, limit={limit_rows}{horizon}"
        self.logger.info(msg)
        print(f" -> {msg} ... ", end="", flush=True)

        # Open: один запрос с ORDER BY end_date ASC — иначе батчи по id портят «ближайшие первые».
        if self._is_open_registry(table):
            params: List[object] = [table, table, limit_rows]
            sql = f"""
                WITH cand AS (
                    SELECT DISTINCT ON (t.contract_number)
                           t.contract_number,
                           {cand_ord_expr} AS ord
                    FROM {table} t
                    WHERE TRUE
                      {end_date_filter}
                      AND EXISTS (
                        SELECT 1
                        FROM user_search_settings uss
                        {okpd_join}
                        WHERE
                            (uss.region_id IS NULL OR uss.region_id = t.region_id)
                            AND NOT EXISTS (
                                SELECT 1
                                FROM stop_words_names swn
                                WHERE swn.user_id = uss.user_id
                                  AND t.auction_name ILIKE '%%' || swn.stop_word || '%%'
                            )
                    )
                    ORDER BY t.contract_number, ord ASC NULLS LAST
                ),
                inserted AS (
                    INSERT INTO document_processing_queue (contract_reg_number, table_source, status)
                    SELECT c.contract_number, %s, 'pending'
                    FROM cand c
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM document_processing_queue q
                        WHERE q.contract_reg_number = c.contract_number
                          AND q.table_source = %s
                    )
                    {self._queue_fz_dedup_sql("c.contract_number", table)}
                    ORDER BY c.ord ASC NULLS LAST
                    ON CONFLICT (contract_reg_number) DO NOTHING
                    LIMIT %s
                    RETURNING id
                )
                SELECT COUNT(*) FROM inserted;
            """
            try:
                rows = self.db.execute_query(sql, tuple(params), fetch=True)
                total_added = rows[0][0] if rows else 0
            except Exception as e:
                self.logger.error(f"[populate] {table}: ошибка {e}")
                total_added = 0
            print(f"OK (added {total_added})", flush=True)
            return total_added

        # Awarded / прочее: батчевый обход по id
        batch_size = int(os.getenv("POPULATE_BATCH_SIZE", "2000"))
        min_id, max_id = self._get_table_id_range(table)
        if min_id is None:
            print("OK (empty table)", flush=True)
            return 0

        total_added = 0
        current_id = min_id

        while current_id <= max_id and total_added < limit_rows:
            batch_end = current_id + batch_size - 1
            remaining = limit_rows - total_added
            params = [table, table, remaining]

            sql = f"""
                WITH cand AS (
                    SELECT DISTINCT ON (t.contract_number)
                           t.contract_number,
                           {cand_ord_expr} AS ord
                    FROM {table} t
                    WHERE t.id BETWEEN {current_id} AND {batch_end}
                      {end_date_filter}
                      AND EXISTS (
                        SELECT 1
                        FROM user_search_settings uss
                        {okpd_join}
                        WHERE
                            (uss.region_id IS NULL OR uss.region_id = t.region_id)
                            AND NOT EXISTS (
                                SELECT 1
                                FROM stop_words_names swn
                                WHERE swn.user_id = uss.user_id
                                  AND t.auction_name ILIKE '%%' || swn.stop_word || '%%'
                            )
                    )
                    ORDER BY t.contract_number, ord DESC NULLS LAST
                ),
                inserted AS (
                    INSERT INTO document_processing_queue (contract_reg_number, table_source, status)
                    SELECT c.contract_number, %s, 'pending'
                    FROM cand c
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM document_processing_queue q
                        WHERE q.contract_reg_number = c.contract_number
                          AND q.table_source = %s
                    )
                    {self._queue_fz_dedup_sql("c.contract_number", table)}
                    ORDER BY c.ord DESC NULLS LAST
                    ON CONFLICT (contract_reg_number) DO NOTHING
                    LIMIT %s
                    RETURNING id
                )
                SELECT COUNT(*) FROM inserted;
            """

            try:
                rows = self.db.execute_query(sql, tuple(params), fetch=True)
                added = rows[0][0] if rows else 0
                total_added += added
                if added > 0:
                    self.logger.info(f"[populate] {table} ids {current_id}-{batch_end}: добавлено {added}")
            except Exception as e:
                self.logger.error(f"[populate] {table} ids {current_id}-{batch_end}: ошибка {e}")

            current_id = batch_end + 1

        print(f"OK (added {total_added})", flush=True)
        return total_added

    def populate_queue(
        self,
        *,
        tables: Optional[Sequence[str]] = None,
        stop_after_first: bool = True,
    ) -> int:
        """
        Пополнение очереди.
        tables — подмножество source_tables (например только high).
        stop_after_first — остановиться после первой таблицы с добавленными задачами.
        Возвращает суммарное число добавленных строк.
        """
        debug_any = os.getenv("DEBUG_POPULATE_ANY") == "1"
        limit_rows = self.populate_limit
        if debug_any:
            self.logger.info("[populate] Режим DEBUG_POPULATE_ANY=1: фильтры пользователя отключены")

        target_tables = list(tables) if tables is not None else self.source_tables
        total_added = 0

        for table in target_tables:
            try:
                import time
                t0 = time.monotonic()
                added = 0
                if debug_any:
                    added = self._populate_debug(table, limit_rows)
                else:
                    added = self._populate_with_filters(table, limit_rows)
                dt = round(time.monotonic() - t0, 3)
                self.logger.info(f"[populate] {table}: завершено за {dt}s, добавлено {added}")
                total_added += added

                if added > 0 and stop_after_first:
                    self.logger.info(
                        f"[populate] Найдено {added} задач в таблице {table}. "
                        f"Прерываем поиск, чтобы обработать их."
                    )
                    break
            except Exception:
                self.logger.exception(f"populate_queue: ошибка при обработке таблицы {table}")

        return total_added

    def populate_high_priority(self, *, stop_after_first: bool = False) -> int:
        """Принудительно подтягивает новые контракты 44/223."""
        self.logger.info("[populate] Пополнение только high-приоритета (новые реестры)")
        return self.populate_queue(
            tables=self.priority.high_tables(),
            stop_after_first=stop_after_first,
        )

    def get_next_batch(
        self,
        worker_id: int,
        batch_size: int,
        force_contract: Optional[str] = None,
        force_table: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        where_extra = ""
        extra_params: List[object] = []
        if force_contract:
            where_extra += " AND contract_reg_number = %s"
            extra_params.append(force_contract)
        if force_table:
            where_extra += " AND table_source = %s"
            extra_params.append(force_table)

        claim_filter, claim_params = self._claim_table_filter_sql()
        where_extra += claim_filter
        extra_params.extend(claim_params)

        from document_processor.queue_claim import claim_batch_ids

        if not force_contract:
            try:
                self.soft_reclassify_pending()
            except Exception as exc:
                self.logger.warning(f"[queue] soft_reclassify skipped: {exc}")
            self.purge_lost_sales_window()

        rows = claim_batch_ids(
            db_execute=self.db.execute_query,
            worker_id=worker_id,
            batch_size=batch_size,
            priority_case=self.priority.sql_order_case(),
            where_extra=where_extra,
            extra_params=extra_params,
        )
        result: List[Dict[str, str]] = []
        for row in rows:
            result.append(
                {
                    "id": row[0],
                    "contract_reg_number": row[1],
                    "table_source": row[2],
                }
            )
        self.logger.info(f"[get_next_batch] worker_id={worker_id}: получено {len(result)} задач")
        return result

    def mark_completed(self, task_id: int) -> None:
        sql = """
            UPDATE document_processing_queue
            SET status = 'completed',
                completed_at = NOW()
            WHERE id = %s
        """
        self.db.execute_query(sql, (task_id,))

    def mark_no_links(self, task_id: int, message: str) -> None:
        sql = """
            UPDATE document_processing_queue
            SET status = 'no_links',
                worker_id = NULL,
                started_at = NULL,
                completed_at = NOW(),
                error_message = %s
            WHERE id = %s
        """
        self.db.execute_query(sql, (message, task_id))

    def mark_requeue_pending(self, task_id: int, message: str = "") -> None:
        """Возвращает задачу в очередь для продолжения обработки."""
        sql = """
            UPDATE document_processing_queue
            SET status = 'pending',
                worker_id = NULL,
                started_at = NULL,
                error_message = %s
            WHERE id = %s
        """
        self.db.execute_query(sql, (message or None, task_id))

    def mark_error(self, task_id: int, error_message: str) -> None:
        sql = """
            UPDATE document_processing_queue
            SET status = 'error',
                error_message = %s,
                completed_at = NOW()
            WHERE id = %s
        """
        self.db.execute_query(sql, (error_message, task_id))
