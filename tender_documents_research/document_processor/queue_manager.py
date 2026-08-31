import os
from typing import List, Dict, Optional, Sequence

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger

from .completion_guard import CompletionGuardDecision, evaluate_completion_guard
from .queue_priority import QueuePriorityPolicy


# Терминальный статус для закупок вне 90-дневного продажного окна.
# Это НЕ ошибка обработки: документы не качаем и не парсим, потому что
# продавать материалы уже поздно ("не успели обработать до окончания").
STATUS_SALES_WINDOW_EXPIRED = "sales_window_expired"


class QueueManager:
    """
    Manages document processing queue operations.
    Delegates to QueueRepository.
    """
    def __init__(self, processing_backend, db, logger=None):
        self.logger = logger or get_logger()
        self.backend = processing_backend
        self.repo = self.backend.queue
        self.db = db
        self.priority = QueuePriorityPolicy()
        self.allowed_table_sources = self._parse_table_sources_env()
        self.source_tables = self._filter_source_tables(self.priority.all_tables_ordered())
        self.populate_limit = int(os.getenv("QUEUE_POPULATE_LIMIT", "10"))
        self.sales_window_days = int(os.getenv("SALES_WINDOW_MIN_DAYS", "90"))


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

    def _populate_debug(self, table: str, limit_rows: int) -> int:
        params: List[object] = [table, table, limit_rows]
        end_date_filter = self._new_tenders_end_date_filter(table, "t")
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
                ORDER BY COALESCE(t.start_date, t.end_date) DESC NULLS LAST
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

    def _new_tenders_end_date_filter(self, table: str, alias: str = "t") -> str:
        """
        Продажное окно для постановки в очередь документов.

        Для open-таблиц: подача должна быть ещё открыта (end_date >= сегодня),
        чтобы закрытые тендеры не занимали очередь открытых воркеров — они уйдут
        сами в awarded и будут обработаны там.
        Для awarded-таблиц: только продажное окно (delivery_end_date).
        """
        days = self.sales_window_days
        is_awarded = "_awarded" in table
        if is_awarded:
            return (
                f" AND COALESCE({alias}.delivery_end_date, {alias}.end_date) IS NOT NULL"
                f" AND COALESCE({alias}.delivery_end_date, {alias}.end_date)::date "
                f">= (CURRENT_DATE - INTERVAL '{days} days')"
            )
        # open table: подача ещё не закрыта
        return (
            f" AND {alias}.end_date IS NOT NULL"
            f" AND {alias}.end_date::date >= CURRENT_DATE"
            f" AND COALESCE({alias}.delivery_end_date, {alias}.end_date)::date "
            f">= (CURRENT_DATE + INTERVAL '{days} days')"
        )

    def purge_lost_sales_window(self) -> int:
        """Снимает pending-задачи, которые уже вне продажного окна.

        Для awarded-таблиц: окно = delivery_end_date (или end_date) >= today + sales_window_days.
        Для open-таблиц: НЕ снимать, если подача ещё открыта (submission_end_at >= CURRENT_DATE).
        Логика: open-тендеры не имеют delivery_end_date — проверяем submission_end_at в dpq.
        """
        tables = [t for t in self.source_tables if t.startswith("reestr_contract_")]
        if not tables:
            return 0
        parts = []
        for table in tables:
            is_awarded = "_awarded" in table
            if is_awarded:
                # Awarded: проверяем только delivery_end_date / end_date (неизменная логика)
                open_submission_guard = ""
            else:
                # Open: не трогать, если подача ещё не истекла по submission_end_at
                open_submission_guard = (
                    "AND NOT ("
                    "  q.submission_end_at IS NOT NULL"
                    "  AND q.submission_end_at >= CURRENT_DATE"
                    ")"
                )
            parts.append(
                f"""
                SELECT q.id
                FROM document_processing_queue q
                JOIN {table} t ON t.contract_number = q.contract_reg_number
                WHERE q.status = 'pending'
                  AND q.table_source = '{table}'
                  AND q.queue_lane != 'crm_active_hot'
                  {open_submission_guard}
                  AND (
                    COALESCE(t.delivery_end_date, t.end_date) IS NULL
                    OR COALESCE(t.delivery_end_date, t.end_date)::date
                       < (CURRENT_DATE + INTERVAL '{self.sales_window_days} days')
                  )
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
                f"sales_window_expired: меньше {self.sales_window_days} дней до окончания",
            ),
            fetch=True,
        ) or []
        count = len(rows)
        if count:
            self.logger.info(f"[queue] снято задач вне продажного окна: {count}")
        return count

    @staticmethod
    def _okpd_prefix_filter_sql(prefixes: list[str], alias: str = "t", mode: str = "exclude") -> str:
        """
        Returns SQL fragment for cand CTE WHERE clause.
        mode='exclude': AND NOT EXISTS (... WHERE okpd LIKE prefix%)
        mode='only':    AND EXISTS     (... WHERE okpd LIKE prefix%)
        """
        if not prefixes:
            return ""
        like_parts = " OR ".join(
            f"cco_pf.main_code LIKE '{p}%%' OR cco_pf.sub_code LIKE '{p}%%'"
            for p in prefixes
        )
        exists_kw = "NOT EXISTS" if mode == "exclude" else "EXISTS"
        return f"""
            AND {exists_kw} (
                SELECT 1 FROM collection_codes_okpd cco_pf
                WHERE cco_pf.id = {alias}.okpd_id
                  AND ({like_parts})
            )"""

    def _populate_with_filters(self, table: str, limit_rows: int) -> int:
        ignore_okpd = os.getenv("IGNORE_OKPD_FILTER") == "1"
        use_prefix = os.getenv("OKPD_MATCH_PREFIX") == "1"
        exclude_okpd = [p.strip() for p in os.getenv("EXCLUDE_OKPD_PREFIXES", "").split(",") if p.strip()]
        only_okpd    = [p.strip() for p in os.getenv("OKPD_ONLY_PREFIXES", "").split(",") if p.strip()]

        if ignore_okpd:
            okpd_join = ""
        else:
            if use_prefix:
                okpd_join = """JOIN okpd_from_users ofu ON ofu.category_id = uss.category_id
                    JOIN collection_codes_okpd cco ON cco.id = t.okpd_id
                                                  AND (cco.main_code LIKE ofu.okpd_code || '%%'
                                                       OR cco.sub_code LIKE ofu.okpd_code || '%%')"""
            else:
                okpd_join = """JOIN okpd_from_users ofu ON ofu.category_id = uss.category_id
                    JOIN collection_codes_okpd cco ON cco.id = t.okpd_id
                                                  AND (cco.main_code = ofu.okpd_code
                                                       OR cco.sub_code = ofu.okpd_code)"""

        okpd_exclude_sql = self._okpd_prefix_filter_sql(exclude_okpd, alias="t", mode="exclude")
        okpd_only_sql    = self._okpd_prefix_filter_sql(only_okpd,    alias="t", mode="only")

        end_date_filter = self._new_tenders_end_date_filter(table, "t")
        horizon = ""
        if end_date_filter:
            try:
                horizon = f", sales_window>={self.sales_window_days}d"
            except ValueError:
                horizon = f", sales_window>={self.sales_window_days}d"
        extra_flags = ""
        if exclude_okpd:
            extra_flags += f", exclude_okpd={exclude_okpd}"
        if only_okpd:
            extra_flags += f", only_okpd={only_okpd}"
        msg = f"[populate] {table}: ignore_okpd={ignore_okpd}, limit={limit_rows}{horizon}{extra_flags}"
        self.logger.info(msg)
        print(f" -> {msg} ... ", end="", flush=True)

        # Батчевый обход по диапазонам ID чтобы не падать по таймауту на больших таблицах
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
            # params order matches the INSERT placeholders:
            # %s(table_source), %s(table for awarded check), %s(table for class check),
            # %s(table for dedup), %s(LIMIT)
            params: List[object] = [table, table, table, table, remaining]

            sql = f"""
                WITH cand AS (
                    SELECT DISTINCT ON (t.contract_number)
                           t.contract_number,
                           COALESCE(t.start_date, t.end_date) AS ord,
                           t.end_date                          AS sub_end,
                           t.initial_price                     AS price
                    FROM {table} t
                    WHERE t.id BETWEEN {current_id} AND {batch_end}
                      {end_date_filter}
                      {okpd_exclude_sql}
                      {okpd_only_sql}
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
                    INSERT INTO document_processing_queue (
                        contract_reg_number, table_source, status,
                        submission_end_at, initial_price,
                        queue_type, priority_class, priority_score,
                        remaining_workdays, deadline_slack,
                        priority_model_version, priority_calculated_at,
                        next_priority_recalc_at
                    )
                    SELECT
                        c.contract_number,
                        %s,
                        'pending',
                        c.sub_end,
                        c.price,
                        -- Initial queue_type: awarded rows go to award_transition
                        CASE WHEN %s LIKE '%%_awarded%%' THEN 'award_transition'
                             WHEN c.sub_end IS NOT NULL AND c.sub_end < NOW() THEN 'historical'
                             ELSE 'commercial_normal'
                        END,
                        -- Initial priority_class: closed → P4, else P2 (recalc fixes it)
                        CASE WHEN %s LIKE '%%_awarded%%' THEN 4
                             WHEN c.sub_end IS NOT NULL AND c.sub_end < NOW() THEN 4
                             ELSE 2
                        END,
                        0,   -- priority_score recalculated by daily sweep
                        NULL, NULL,
                        'v1_formula',
                        NOW(),
                        NOW() + INTERVAL '5 minutes'  -- recalc shortly after insert
                    FROM cand c
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM document_processing_queue q
                        WHERE q.contract_reg_number = c.contract_number
                          AND q.table_source = %s
                    )
                    {self._queue_fz_dedup_sql("c.contract_number", table)}
                    ORDER BY c.ord DESC NULLS LAST
                    LIMIT %s
                    ON CONFLICT (contract_reg_number) DO NOTHING
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
                # Продолжаем со следующим батчем

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

    def _get_next_batch(
        self,
        worker_id: int,
        batch_size: int,
        force_contract: Optional[str] = None,
        force_table: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Internal helper to get batch from repository."""
        if not force_contract:
            try:
                self.soft_reclassify_pending()
            except Exception as exc:
                self.logger.warning(f"[queue] soft_reclassify skipped: {exc}")
            self.purge_lost_sales_window()

        return self.repo.claim_batch(
            worker_id=worker_id,
            batch_size=batch_size,
            force_contract=force_contract,
            force_table=force_table,
            queue_lanes=self._resolve_worker_lanes(worker_id)
        )

    def get_next_batch(
        self,
        worker_id: int,
        batch_size: int,
        force_contract: Optional[str] = None,
        force_table: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        rows = self._get_next_batch(worker_id, batch_size, force_contract, force_table)
        result: List[Dict[str, str]] = []
        for row in rows:
            result.append({
                "id":                  row[0],
                "contract_reg_number": row[1],
                "table_source":        row[2],
                "queue_lane":          row[3] if len(row) > 3 else None,
                "priority_class":      row[4] if len(row) > 4 else None,
                "priority_score":      row[5] if len(row) > 5 else None,
            })
        if result:
            lane_summary = ", ".join(
                f"{r.get('queue_lane','?')}(P{r.get('priority_class','?')}·{r.get('priority_score','?')})"
                for r in result
            )
            self.logger.info(
                f"[get_next_batch] worker_id={worker_id}: {len(result)} задач [{lane_summary}]"
            )
        else:
            self.logger.info(f"[get_next_batch] worker_id={worker_id}: задач нет")
        return result

    def _resolve_worker_lanes(self, worker_id: int) -> Optional[List[str]]:
        """
        Resolve which queue_lanes this worker should claim.

        Env QUEUE_LANES overrides everything (comma-separated).
        Env QUEUE_LANES_FLEX=1 enables flex mode:
          if crm_active_hot or open_active tasks exist → take those;
          otherwise fall back to awarded_recent / historical_awarded.

        Default logic by table source:
          - awarded-only workers → awarded_recent, historical_awarded
          - open workers         → crm_active_hot, open_active
          - no restriction       → crm_active_hot, open_active (daemon takes all)
        """
        # Explicit override
        raw = (os.getenv("QUEUE_LANES") or "").strip()
        if raw:
            lanes = [l.strip() for l in raw.split(",") if l.strip()]
            if lanes:
                return lanes

        # Flex mode (worker 17 pattern)
        if os.getenv("QUEUE_LANES_FLEX") == "1":
            return self._flex_lanes()

        # Default: awarded-only vs open
        if self.allowed_table_sources and all("_awarded" in t for t in self.allowed_table_sources):
            return ["awarded_recent", "historical_awarded"]

        return ["crm_active_hot", "open_active"]

    def _flex_lanes(self) -> List[str]:
        """
        Flex: prefer open/CRM lanes, fall back to awarded if empty.
        Returns lanes that have at least one pending task; if none, returns awarded.
        """
        try:
            rows = self.db.execute_query(
                "tender_monitor",
                """
                SELECT queue_lane, COUNT(*) AS cnt
                FROM document_processing_queue
                WHERE status = 'pending'
                  AND queue_lane IN ('crm_active_hot', 'open_active', 'awarded_recent', 'historical_awarded')
                GROUP BY queue_lane
                """,
                fetch=True,
            ) or []
            counts = {r[0]: int(r[1]) for r in rows}
        except Exception:
            counts = {}

        if counts.get("crm_active_hot", 0) > 0 or counts.get("open_active", 0) > 0:
            return ["crm_active_hot", "open_active"]
        return ["awarded_recent", "historical_awarded"]

    def mark_completed(
        self,
        task_id: int,
        *,
        status_rows: Sequence[tuple] | None = None,
        retryable_failure: bool = False,
        status_read_failed: bool = False,
        task_eligible: bool = True,
    ) -> CompletionGuardDecision:
        decision = evaluate_completion_guard(
            status_rows,
            retryable_failure=retryable_failure,
            status_read_failed=status_read_failed,
            task_eligible=task_eligible,
        )
        if not decision.allowed:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning(
                    f"[{task_id}] completion blocked: policy={decision.policy_version} "
                    f"reasons={decision.blocking_reasons} "
                    f"statuses={decision.observed_statuses}"
                )
            return decision
        self.repo.mark_task_completed(task_id)
        return decision

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
