"""
Оркестрация sync recouped XML → реестр.

Находит контракт (включая awarded), обновляет поля, при необходимости
переносит в разыгранные.

Integrity (2026-08-13):
- RGK/contract-registry XML must NOT create placeholder procurement cards
  with okpd_id=NULL / title "Контракт {n}" / region_id=NULL.
- New canonical insert requires okpd_id + real auction_name from raw XML.
- Unresolved contracts are recorded in rgk_contract_unresolved.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from psycopg2 import errors as pg_errors

from utils.logger_config import get_logger

from database_work.contract_awarded_promoter import ContractAwardedPromoter
from database_work.contract_location import ContractLocation
from database_work.contract_registry_locator import ContractRegistryLocator
from database_work.contract_registry_updater import ContractRegistryUpdater
from database_work.database_connection import DatabaseManager
from database_work.database_operations import DatabaseOperations
from database_work.registry_tables import persistence_payload, tables_for_fz

logger = get_logger()

PLACEHOLDER_TITLE_PREFIX = "Контракт "


class RecoupedContractSync:
    """Единая точка для обновления контракта из RGK/recouped."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self._db = db_manager or DatabaseManager()
        self._locator = ContractRegistryLocator(self._db)
        self._updater = ContractRegistryUpdater(self._db)
        self._promoter = ContractAwardedPromoter(self._db)

    def find(self, contract_number: str, fz_type: Optional[str] = None) -> Optional[ContractLocation]:
        if fz_type:
            return self._locator.find_in_fz_one_query(fz_type, contract_number)
        return self._locator.find_in_fz_one_query("44", contract_number)

    def find_44_one_query(self, contract_number: str) -> Optional[ContractLocation]:
        """44-FZ-only lifecycle lookup with unchanged priority semantics."""
        return self._locator.find_in_fz_one_query("44", contract_number)

    def apply_update(
        self,
        contract_number: str,
        fields: Dict[str, Any],
        fz_type: Optional[str] = None,
        known_location: Optional[ContractLocation] = None,
        location_lookup_done: bool = False,
    ) -> Optional[ContractLocation]:
        """
        1) Найти: main → unknown → unclear → awarded (completed не ищем)
        2) UPDATE на месте (в т.ч. awarded; completed — нет)
        3) Если unknown/unclear/main/commission + подрядчик + delivery_end → awarded
        4) Если не найден — insert ONLY when canonical integrity fields present
        """
        location = known_location
        if location is None and not location_lookup_done:
            location = self.find(contract_number, fz_type=fz_type)
        if location is None:
            logger.warning(
                f"Recouped sync: контракт {contract_number} не найден, пробуем канонический insert"
            )
            location = self._insert_new_contract(contract_number, fields, fz_type)
            if location is None:
                return None
        if not self._updater.update(location, fields):
            return None

        if self._promoter.should_promote(location, fields):
            promoted = self._promoter.promote(location)
            return promoted or location

        return location

    def record_non_target_once(
        self, contract_number: str, fields: Dict[str, Any]
    ) -> None:
        """Record an expected 44-FZ non-target classification once."""
        self._record_unresolved(contract_number, fields, "44", "MISSING_OKPD_ID")

    def _canonical_okpd_id(self, fields: Dict[str, Any]) -> Optional[int]:
        if fields.get("okpd_id") is not None:
            try:
                return int(fields["okpd_id"])
            except (TypeError, ValueError):
                return None
        return None

    def _canonical_title(self, fields: Dict[str, Any], contract_number: str) -> Optional[str]:
        title = fields.get("auction_name")
        if not title or not str(title).strip():
            return None
        title = str(title).strip()
        if title.startswith(PLACEHOLDER_TITLE_PREFIX):
            return None
        if title == f"{PLACEHOLDER_TITLE_PREFIX}{contract_number}":
            return None
        return title

    def _record_unresolved(
        self,
        contract_number: str,
        fields: Dict[str, Any],
        fz_type: Optional[str],
        reason: str,
    ) -> None:
        """Best-effort write to reconciliation table; never raises into caller."""
        okpd_codes: List[str] = []
        raw_codes = fields.get("okpd_codes") or fields.get("okpd_codes_list")
        if isinstance(raw_codes, list):
            okpd_codes = [str(c).strip() for c in raw_codes if c and str(c).strip()]
        elif fields.get("okpd_code"):
            okpd_codes = [str(fields["okpd_code"]).strip()]
        payload = {
            k: v for k, v in fields.items()
            if k not in ("okpd_codes_list",) and not callable(v)
        }
        safe_payload = json.loads(json.dumps(payload, default=str))

        for attempt in range(1, 4):
            try:
                cur = self._db.connection.cursor()
                cur.execute(
                """
                INSERT INTO rgk_contract_unresolved (
                    fz_type, contract_number, notification_number, reestr_number,
                    contract_subject, okpd_codes, okpd_codes_json, raw_file,
                    tender_link, reason, payload_json, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s,
                    %s, %s, %s::jsonb, NOW()
                )
                ON CONFLICT (fz_type, contract_number) DO UPDATE SET
                    notification_number = EXCLUDED.notification_number,
                    reestr_number = EXCLUDED.reestr_number,
                    contract_subject = COALESCE(EXCLUDED.contract_subject, rgk_contract_unresolved.contract_subject),
                    okpd_codes = EXCLUDED.okpd_codes,
                    okpd_codes_json = EXCLUDED.okpd_codes_json,
                    raw_file = COALESCE(EXCLUDED.raw_file, rgk_contract_unresolved.raw_file),
                    tender_link = COALESCE(EXCLUDED.tender_link, rgk_contract_unresolved.tender_link),
                    reason = EXCLUDED.reason,
                    payload_json = EXCLUDED.payload_json,
                    updated_at = NOW()
                """,
                (
                    fz_type or "",
                    contract_number,
                    fields.get("notification_number"),
                    fields.get("reestr_number"),
                    fields.get("auction_name") or fields.get("contract_subject"),
                    okpd_codes or None,
                    json.dumps(okpd_codes, ensure_ascii=False),
                    fields.get("raw_file"),
                    fields.get("tender_link"),
                    reason,
                    json.dumps(safe_payload, ensure_ascii=False),
                ),
                )
                self._db.connection.commit()
                if attempt > 1:
                    logger.info(
                        f"RGK unresolved retry succeeded for {contract_number} "
                        f"on attempt {attempt}"
                    )
                return
            except (pg_errors.DeadlockDetected, pg_errors.SerializationFailure) as exc:
                self._db.connection.rollback()
                if attempt == 3:
                    logger.error(
                        f"RGK unresolved final transient failure for "
                        f"{contract_number} after {attempt} attempts: {exc}"
                    )
                    return
                logger.warning(
                    f"RGK unresolved transient failure for {contract_number}; "
                    f"retry {attempt}/2: {exc}"
                )
                time.sleep(0.1 * attempt)
            except Exception as exc:
                try:
                    self._db.connection.rollback()
                except Exception:
                    pass
                logger.error(f"RGK unresolved record failed for {contract_number}: {exc}")
                return

    def _insert_new_contract(
        self,
        contract_number: str,
        fields: Dict[str, Any],
        fz_type: Optional[str],
    ) -> Optional[ContractLocation]:
        if not fz_type:
            logger.error(f"Recouped insert: не передан тип ФЗ для {contract_number}")
            return None

        okpd_id = self._canonical_okpd_id(fields)
        title = self._canonical_title(fields, contract_number)
        if okpd_id is None or title is None:
            reason = "MISSING_OKPD_ID" if okpd_id is None else "MISSING_REAL_TITLE"
            if okpd_id is None and title is None:
                reason = "MISSING_OKPD_AND_TITLE"
            logger.warning(
                f"Recouped insert BLOCKED for {contract_number}: {reason} "
                f"(no placeholder canonical row)"
            )
            self._record_unresolved(contract_number, fields, fz_type, reason)
            return None

        payload = persistence_payload(fz_type, fields)
        payload["contract_number"] = contract_number
        payload["okpd_id"] = okpd_id
        payload["auction_name"] = title
        payload.setdefault("initial_price", 0)
        # Never invent placeholder titles
        if str(payload.get("auction_name", "")).startswith(PLACEHOLDER_TITLE_PREFIX):
            self._record_unresolved(contract_number, fields, fz_type, "PLACEHOLDER_TITLE_BLOCKED")
            return None

        if fz_type == "44":
            payload.setdefault(
                "tender_link",
                f"https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber={contract_number}",
            )
        elif fz_type == "223":
            payload.setdefault(
                "tender_link",
                f"https://zakupki.gov.ru/223/contract/public/contract/view/general-information.html?regNumber={contract_number}",
            )

        ops = DatabaseOperations(db_manager=self._db)
        try:
            if fz_type == "44":
                record_id = ops.insert_reestr_contract_44_fz(payload)
            elif fz_type == "223":
                record_id = ops.insert_reestr_contract_223_fz(payload)
            else:
                logger.error(f"Recouped insert: неподдерживаемый тип ФЗ {fz_type} для {contract_number}")
                return None
        except Exception as exc:
            logger.error(f"Recouped insert error for {contract_number}: {exc}")
            self._record_unresolved(contract_number, fields, fz_type, f"INSERT_ERROR:{exc}")
            return None

        if not record_id:
            logger.error(f"Recouped insert: не удалось получить id для {contract_number}")
            return None

        table_name = tables_for_fz(fz_type).main
        logger.info(
            f"Recouped sync: создан канонический контракт {contract_number} "
            f"в {table_name} (id={record_id}, okpd_id={okpd_id})"
        )
        return ContractLocation(
            fz_type=fz_type,
            table_name=table_name,
            record_id=record_id,
            contract_number=contract_number,
        )
