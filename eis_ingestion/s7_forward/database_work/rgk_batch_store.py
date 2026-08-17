"""Bulk persistence for one 44-FZ RGK batch. One COMMIT per persist()."""
from __future__ import annotations

import json
from typing import Any, Optional

from psycopg2 import IntegrityError
from psycopg2.extras import execute_values

from database_work.rgk_batch_sql import (
    ALLOWED_TABLES_44,
    BATCH_UPDATE_COLUMNS,
    UPDATE_VALUE_TEMPLATE,
    build_batch_update_sql,
    build_contractor_lookup_sql,
    build_filename_insert_sql,
    build_filename_lookup_sql,
    build_okpd_lookup_sql,
    build_registry_lookup_sql,
    build_unresolved_lookup_sql,
    build_unresolved_upsert_sql,
    merge_registry_priority,
)
from database_work.rgk_plan import BatchPlan
from database_work.registry_tables import lookup_order, persistence_payload, tables_for_fz
from parsing_xml.rgk_record import RGKRecord
from utils.logger_config import get_logger

logger = get_logger()
TABLES_44 = tables_for_fz("44")


class StatementCounter:
    def __init__(self) -> None:
        self.selects = 0
        self.updates = 0
        self.inserts = 0
        self.commits = 0
        self.parse_passes = 0

    def note(self, sql: str) -> None:
        head = sql.lstrip().split(None, 1)[0].upper() if sql and sql.strip() else ""
        if head == "SELECT":
            self.selects += 1
        elif head == "UPDATE":
            self.updates += 1
        elif head in {"INSERT", "DELETE"}:
            self.inserts += 1
        elif head in {"SET", "SAVEPOINT", "RELEASE", "ROLLBACK"}:
            return

    def note_commit(self) -> None:
        self.commits += 1


class RgkBatchStore:
    def __init__(self, db_manager, counter: Optional[StatementCounter] = None) -> None:
        self._db = db_manager
        self.counter = counter or StatementCounter()

    def _execute(self, cursor, sql: str, params=None):
        self.counter.note(sql)
        return cursor.execute(sql, params)

    def lookup_filenames(self, names: list[str]) -> set[str]:
        if not names:
            return set()
        with self._db.connection.cursor() as cursor:
            self._execute(cursor, build_filename_lookup_sql(), (names,))
            return {str(row[0]) for row in cursor.fetchall()}

    def lookup_okpd(self, codes: list[str]) -> dict[str, int]:
        unique = [code for code in dict.fromkeys(codes) if code]
        if not unique:
            return {}
        with self._db.connection.cursor() as cursor:
            self._execute(cursor, build_okpd_lookup_sql(), (unique,))
            return {str(row[1]): int(row[0]) for row in cursor.fetchall()}

    def lookup_contractors(self, inns: list[str]) -> dict[str, int]:
        unique = [inn for inn in dict.fromkeys(inns) if inn]
        if not unique:
            return {}
        with self._db.connection.cursor() as cursor:
            self._execute(cursor, build_contractor_lookup_sql(), (unique,))
            return {str(row[1]): int(row[0]) for row in cursor.fetchall()}

    def lookup_registry(self, numbers: list[str]) -> dict[str, dict]:
        unique = [number for number in dict.fromkeys(numbers) if number]
        if not unique:
            return {}
        rows_by_table: dict[str, list] = {}
        with self._db.connection.cursor() as cursor:
            remaining = list(unique)
            for table_name in lookup_order(TABLES_44):
                if not remaining:
                    break
                self._execute(cursor, build_registry_lookup_sql(table_name), (remaining,))
                rows = cursor.fetchall()
                rows_by_table[table_name] = rows
                found = {str(row[1]).strip() for row in rows if row[1] is not None}
                remaining = [number for number in remaining if number not in found]
        return merge_registry_priority(rows_by_table)

    def lookup_unresolved(self, numbers: list[str]) -> dict[str, dict]:
        unique = [number for number in dict.fromkeys(numbers) if number]
        if not unique:
            return {}
        with self._db.connection.cursor() as cursor:
            self._execute(cursor, build_unresolved_lookup_sql(), ("44", unique))
            found: dict[str, dict] = {}
            for row in cursor.fetchall():
                found[str(row[0])] = {
                    "reason": row[1],
                    "payload_json": row[2],
                    "okpd_codes": row[3] or [],
                    "contract_subject": row[4],
                }
            return found

    def apply(
        self,
        records: list[RGKRecord],
        *,
        known_filenames: set[str],
        okpd_map: dict[str, int],
        contractor_map: dict[str, int],
        registry_map: dict[str, dict],
        unresolved_map: dict[str, dict],
        version_cache,
    ):
        from parsing_xml.xml_parser_recouped_contract import _remember_non_target_version
        from database_work.rgk_plan import plan_44_batch

        if records:
            with self._db.connection.cursor() as cursor:
                self._ensure_contractors(cursor, records, contractor_map)
        plan = plan_44_batch(
            records,
            known_filenames=known_filenames,
            okpd_map=okpd_map,
            contractor_map=contractor_map,
            registry_map=registry_map,
            unresolved_map=unresolved_map,
            version_cache=version_cache,
        )
        if plan.filenames or plan.unresolved or plan.updates or plan.inserts or plan.promotes:
            self.persist(plan, contractor_map)
        elif records:
            try:
                self._db.connection.rollback()
            except Exception:
                pass
        for key in plan.remember_versions:
            _remember_non_target_version(key)
        return plan

    def persist(self, plan: BatchPlan, contractor_map: dict[str, int]) -> None:
        connection = self._db.connection
        try:
            with connection.cursor() as cursor:
                self._ensure_contractors(cursor, plan.records, contractor_map)
                for record in plan.records:
                    if record.contractor_inn and record.contractor_inn in contractor_map:
                        record.contractor_id = contractor_map[record.contractor_inn]
                for write in plan.inserts:
                    if write.fields.get("contractor_id") is None:
                        inn = next(
                            (
                                rec.contractor_inn
                                for rec in plan.records
                                if rec.contract_number == write.contract_number and rec.contractor_inn
                            ),
                            None,
                        )
                        if inn and inn in contractor_map:
                            write.fields["contractor_id"] = contractor_map[inn]
                self._insert_canonical(cursor, plan)
                self._update_changed(cursor, plan)
                self._promote(cursor, plan)
                self._upsert_unresolved(cursor, plan)
                self._insert_links(cursor, plan)
                self._insert_filenames(cursor, plan.filenames)
            connection.commit()
            self.counter.note_commit()
        except Exception:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET session_replication_role = 'origin'")
            except Exception:
                pass
            try:
                connection.rollback()
            except Exception:
                pass
            raise

    def _ensure_contractors(self, cursor, records: list[RGKRecord], contractor_map: dict[str, int]) -> None:
        seen: set[str] = set()
        for record in records:
            inn = record.contractor_inn
            if not inn or inn in contractor_map or inn in seen:
                continue
            seen.add(inn)
            contractor_id = self._insert_contractor(cursor, record.contractor_fields)
            if contractor_id is not None:
                contractor_map[inn] = contractor_id

    def _insert_contractor(self, cursor, fields: dict[str, Any]) -> Optional[int]:
        inn = str(fields.get("inn") or "").strip()
        if not inn:
            return None
        full_name = (fields.get("full_name") or "").strip() or None
        short_name = (fields.get("short_name") or "").strip() or (full_name[:500] if full_name else None)
        if not short_name:
            short_name = inn
        payload = {
            "short_name": short_name[:500],
            "full_name": (full_name or short_name)[:1000],
            "inn": inn[:20],
            "kpp": (str(fields.get("kpp")).strip()[:20] if fields.get("kpp") else None),
            "legal_address": (
                str(fields.get("legal_address")).strip()[:1000] if fields.get("legal_address") else None
            ),
            "email": (str(fields.get("email")).strip()[:255] if fields.get("email") else None),
            "phone": (str(fields.get("phone")).strip()[:100] if fields.get("phone") else None),
        }
        self._execute(cursor, "SAVEPOINT rgk_contractor")
        try:
            self._execute(
                cursor,
                """
                INSERT INTO contractor
                    (short_name, full_name, inn, kpp, legal_address, email, phone)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                tuple(payload.values()),
            )
            contractor_id = int(cursor.fetchone()[0])
            self._execute(cursor, "RELEASE SAVEPOINT rgk_contractor")
            return contractor_id
        except IntegrityError:
            self._execute(cursor, "ROLLBACK TO SAVEPOINT rgk_contractor")
            self._execute(cursor, "SELECT id FROM contractor WHERE inn = %s", (inn,))
            row = cursor.fetchone()
            return int(row[0]) if row else None

    def _insert_canonical(self, cursor, plan: BatchPlan) -> None:
        for write in plan.inserts:
            payload = persistence_payload("44", write.fields)
            payload["contract_number"] = write.contract_number
            payload.setdefault("initial_price", 0)
            columns = list(payload.keys())
            sql = (
                f"INSERT INTO {TABLES_44.main} ({', '.join(columns)}) "
                f"VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id"
            )
            self._execute(cursor, sql, tuple(payload.values()))
            row = cursor.fetchone()
            write.record_id = int(row[0])
            write.table_name = TABLES_44.main

    def _update_changed(self, cursor, plan: BatchPlan) -> None:
        by_table: dict[str, list] = {}
        for write in plan.updates:
            if write.table_name not in ALLOWED_TABLES_44 or write.record_id is None:
                continue
            by_table.setdefault(write.table_name, []).append(write)
        for table_name, writes in by_table.items():
            rows = []
            for write in writes:
                fields = write.fields
                rows.append(
                    (
                        write.record_id,
                        fields.get("final_price"),
                        fields.get("contractor_id"),
                        fields.get("delivery_start_date"),
                        fields.get("delivery_end_date"),
                        fields.get("auction_name"),
                        fields.get("okpd_id"),
                        fields.get("initial_price"),
                        fields.get("guarantee_amount"),
                        fields.get("region_id"),
                    )
                )
            execute_values(
                cursor,
                build_batch_update_sql(table_name, BATCH_UPDATE_COLUMNS),
                rows,
                template=UPDATE_VALUE_TEMPLATE,
            )
            self.counter.updates += 1

    def _promote(self, cursor, plan: BatchPlan) -> None:
        awarded = TABLES_44.awarded
        by_source: dict[str, list[int]] = {}
        for write in plan.promotes:
            if write.record_id is None or write.table_name == awarded:
                continue
            if write.table_name not in ALLOWED_TABLES_44:
                continue
            by_source.setdefault(write.table_name, []).append(int(write.record_id))
        for source, ids in by_source.items():
            self._execute(
                cursor,
                f"INSERT INTO {awarded} SELECT * FROM {source} "
                f"WHERE id = ANY(%s) AND NOT EXISTS ("
                f"SELECT 1 FROM {awarded} a WHERE a.id = {source}.id)",
                (ids,),
            )
            self._execute(cursor, "SET session_replication_role = 'replica'")
            self._execute(cursor, f"DELETE FROM {source} WHERE id = ANY(%s)", (ids,))
            self._execute(cursor, "SET session_replication_role = 'origin'")
            for write in plan.promotes:
                if write.record_id in ids:
                    write.table_name = awarded

    def _upsert_unresolved(self, cursor, plan: BatchPlan) -> None:
        if not plan.unresolved:
            return
        rows = []
        for item in plan.unresolved:
            fields = item.fields
            codes = list(fields.get("okpd_codes") or [])
            safe_payload = json.loads(json.dumps(fields, default=str))
            rows.append(
                (
                    "44",
                    item.contract_number,
                    fields.get("notification_number"),
                    fields.get("reestr_number"),
                    fields.get("auction_name") or fields.get("contract_subject"),
                    codes or None,
                    json.dumps(codes, ensure_ascii=False),
                    fields.get("raw_file"),
                    fields.get("tender_link"),
                    item.reason,
                    json.dumps(safe_payload, ensure_ascii=False),
                )
            )
        execute_values(
            cursor,
            build_unresolved_upsert_sql(),
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, NOW())",
        )
        self.counter.inserts += 1

    def _insert_links(self, cursor, plan: BatchPlan) -> None:
        links = [item for item in plan.links() if item.get("document_links")]
        if not links:
            return
        rows = [
            (
                item.get("file_name"),
                item.get("document_links"),
                item.get("contract_id"),
                item.get("contract_number"),
            )
            for item in links
        ]
        execute_values(
            cursor,
            "INSERT INTO links_documentation_44_fz "
            "(file_name, document_links, contract_id, contract_number) VALUES %s",
            rows,
        )
        self.counter.inserts += 1

    def _insert_filenames(self, cursor, names: list[str]) -> None:
        unique = [name for name in dict.fromkeys(names) if name]
        if not unique:
            return
        execute_values(cursor, build_filename_insert_sql(), [(name,) for name in unique])
        self.counter.inserts += 1
