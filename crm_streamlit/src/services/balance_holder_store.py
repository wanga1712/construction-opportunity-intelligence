"""Сегмент балансодержателя в CRM (crm_external_entities)."""
import json
from typing import Dict, Optional, Tuple

from loguru import logger

from modules.crm.analytics.inn_normalize import normalize_inn
from src.constants.balance_holder_registries import SOURCE_TYPE

_KEY_MAIN = "balance_holder_tab"
_KEY_HOUSING = "balance_holder_housing_sub"


def _auto_segment(full_name: str, legal_form: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Эвристика до ручной разметки."""
    text = f"{full_name or ''} {legal_form or ''}".upper()
    if "ЖИЛИЩНИК" in text or ("ГБУ" in text and "ЖИЛ" in text):
        return "housing", "gbu_zhilischnik"
    if any(k in text for k in ("ГБУ", "ГКУ", "ФГБУ", "МУП", "ГУП", "БЮДЖЕТ", "ГОСУДАР")):
        return "state", None
    if any(k in text for k in ("ТСЖ", "ЖСК", "НЕКОММЕР")):
        return "housing", "housing_noncommercial"
    if "ЖИЛ" in text and any(k in text for k in ("ООО", "АО", "ПАО")):
        return "housing", "housing_commercial"
    if any(k in text for k in ("ООО", "АО", "ПАО", "ЗАО")):
        return "commercial", None
    return None, None


class BalanceHolderStore:
    """Чтение/запись сегмента балансодержателя."""

    def __init__(self, crm_db):
        self.db = crm_db
        self._cache: Optional[Dict[str, Tuple[Optional[str], Optional[str]]]] = None

    def invalidate_cache(self) -> None:
        self._cache = None

    def load_map(self) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
        if self._cache is not None:
            return self._cache
        if not self.db:
            self._cache = {}
            return self._cache
        try:
            rows = self.db.execute_query(
                """
                SELECT source_key, payload
                FROM crm_external_entities
                WHERE source_type = %s
                """,
                (SOURCE_TYPE,),
            )
            result: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
            for row in rows:
                payload = row.get("payload") or {}
                if isinstance(payload, str):
                    payload = json.loads(payload)
                key = normalize_inn(row["source_key"]) or row["source_key"]
                result[key] = (
                    payload.get(_KEY_MAIN),
                    payload.get(_KEY_HOUSING),
                )
            self._cache = result
            return result
        except Exception as e:
            logger.error(f"BalanceHolderStore.load_map: {e}")
            self._cache = {}
            return self._cache

    def get_segment(
        self,
        inn: str,
        full_name: str = "",
        legal_form: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        canonical = normalize_inn(inn) or inn
        manual = self.load_map().get(canonical)
        if manual and manual[0]:
            return manual
        return _auto_segment(full_name, legal_form)

    def save_segment(
        self,
        inn: str,
        main_tab: Optional[str],
        housing_sub: Optional[str] = None,
    ) -> bool:
        if not self.db:
            return False
        canonical = normalize_inn(inn)
        if not canonical:
            return False
        inn = canonical
        try:
            payload = {
                _KEY_MAIN: main_tab,
                _KEY_HOUSING: housing_sub if main_tab == "housing" else None,
            }
            payload_json = json.dumps(payload, ensure_ascii=False)
            self.db.execute_query(
                """
                INSERT INTO crm_external_entities (source_type, source_key, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (source_type, source_key)
                DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (SOURCE_TYPE, inn, payload_json),
            )
            self.load_map()[inn] = (main_tab, housing_sub)
            return True
        except Exception as e:
            logger.error(f"BalanceHolderStore.save_segment({inn}): {e}")
            return False
