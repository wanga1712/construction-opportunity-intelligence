"""Service for the Objects CRM page."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from loguru import logger

from modules.crm.analytics.tender_superuser_settings import TenderSuperuserSettings
from modules.crm.repositories.objects_index_repository import ObjectsIndexRepository
from src.constants.object_segments import OBJECT_SEGMENT_TABS, OBJECT_SOURCE_OPTIONS
from src.services.object_ai_classification_store import apply_ai_classifications
from src.services.object_ai_scores import apply_object_ai_scores
from src.services.object_category_labels import apply_object_category_labels
from src.services.object_lifecycle import is_awarded, is_lost_for_sales_window
from src.services.object_models import ObjectViewItem
from src.services.object_pipeline_stage import apply_pipeline_stages
from src.services.object_enrich import enrich_tender_items
from src.services.expertise_enrich import enrich_objects_from_expertise
from src.services.docs_match_preview import apply_match_previews
from src.services.object_subcategory_links import sync_for_items as sync_object_subcategories
from src.services.profile_decisions_sync import sync_profile_decisions
from src.services.objects_loader import load_curated_objects
from src.services.objects_mapper import index_row_to_item
from src.services.profiled_search import ProfiledSearchService


class ObjectsService:
    """Cached object list: prefer crm_objects_index, otherwise load directly."""

    def __init__(self, radar_db=None, tender_db=None, crm_db=None):
        self.radar_db = radar_db
        self.tender_db = tender_db
        self.crm_db = crm_db
        self._index_repo = ObjectsIndexRepository(crm_db) if crm_db else None
        self._items: List[ObjectViewItem] = []
        self._settings: Optional[TenderSuperuserSettings] = None
        self._region_names: Dict[int, str] = {}
        self._loaded = False
        self._from_index = False
        self._last_dynamic_enrich_at: float = 0.0
        self._dynamic_enrich_ttl_sec: int = 300
        self.last_error: Optional[str] = None

    def index_meta(self) -> Dict:
        if not self._index_repo:
            return {}
        return self._index_repo.get_meta()

    def has_index(self) -> bool:
        meta = self.index_meta()
        return bool(meta.get("row_count"))

    def load_sync(self, force: bool = False, search_query: str = "") -> bool:
        if self._loaded and not force and not search_query:
            # Не дергаем БД на каждом rerun UI: динамическое обогащение
            # обновляем по TTL либо при принудительном force refresh.
            self._apply_dynamic_enrichments_if_needed(force=False)
            return True

        self.last_error = None
        try:
            if self._index_repo and self._index_repo.is_available():
                if not self._index_repo.get_meta().get("row_count") and not force:
                    self._items = []
                    self._loaded = True
                    self._from_index = False
                    return True
                rows = (
                    self._index_repo.search(search_query)
                    if search_query.strip()
                    else self._index_repo.load_all()
                )
                self._items = [index_row_to_item(r) for r in rows]
                self._from_index = True
                self._enrich_from_registry()
                self._apply_dynamic_enrichments_if_needed(force=True)
                self._loaded = True
                return True

            items, settings, region_names = load_curated_objects(
                self.radar_db,
                self.tender_db,
            )
            self._items = items
            self._settings = settings
            self._region_names = region_names
            self._from_index = False
            self._enrich_from_registry()
            self._apply_dynamic_enrichments_if_needed(force=True)
            self._loaded = True
            return True
        except Exception as exc:
            logger.error(f"ObjectsService.load_sync: {exc}", exc_info=True)
            self.last_error = str(exc)
            return False

    def _apply_dynamic_enrichments_if_needed(self, *, force: bool) -> None:
        now = time.time()
        if not force and (now - self._last_dynamic_enrich_at) < self._dynamic_enrich_ttl_sec:
            return
        enrich_objects_from_expertise(self.tender_db, self._items)
        apply_match_previews(self.tender_db, self._items)
        apply_object_category_labels(self._items)
        apply_object_ai_scores(self._items)
        apply_ai_classifications(self._items, self.crm_db)
        apply_pipeline_stages(self._items)
        self._apply_quality_medals()
        try:
            sync_object_subcategories(self.crm_db, self._items, contour_code="procurement")
        except Exception as exc:
            logger.warning(f"sync_object_subcategories: {exc}")
        try:
            sync_profile_decisions(self.crm_db, self._items, limit=500)
        except Exception as exc:
            logger.warning(f"sync_profile_decisions: {exc}")
        self._last_dynamic_enrich_at = now

    def _apply_quality_medals(self) -> None:
        """AI-driven medals for card status."""
        for item in self._items:
            doc_matches = int(item.doc_matches or 0)
            matched_files = int(item.matched_files or 0)
            ai_score = int(item.ai_priority_score or 0)
            ai_confidence = int(item.ai_classification_confidence or 0)
            ai_delivery = (item.ai_delivery_chance or "").strip().lower()
            ai_action = (item.ai_sales_action or "").strip().lower()
            has_expertise = bool((item.expertise_number or "").strip())
            has_participants = bool((item.customer_inn or "").strip() and (item.contractor_inn or "").strip())
            volume_signal = (item.ai_volume_signal or "").strip().lower()
            docs_volume = (item.docs_volume_preview or "").strip().lower()
            has_volume = (
                bool(volume_signal and volume_signal not in {"неизвестно", "unknown"})
                or bool(docs_volume and docs_volume not in {"объём не извлечён", "volume not extracted"})
            )

            reasons: list[str] = []
            if doc_matches > 0:
                reasons.append(f"doc_matches={doc_matches}")
            if matched_files > 0:
                reasons.append(f"matched_files={matched_files}")
            if ai_score > 0:
                reasons.append(f"ai={ai_score}")
            if ai_confidence > 0:
                reasons.append(f"conf={ai_confidence}")
            if ai_delivery:
                reasons.append(f"chance={ai_delivery}")
            if has_volume:
                reasons.append("volume=yes")
            if ai_action:
                reasons.append(f"action={ai_action}")

            if (
                doc_matches > 0
                and has_volume
                and ai_score >= 78
                and ai_confidence >= 60
                and ai_delivery in {"высокий", "high"}
                and ai_action in {"direct_bid", "wait_contractor"}
            ):
                medal = "gold"
            elif (
                doc_matches > 0
                and (
                    ai_score >= 58
                    or ai_confidence >= 55
                    or matched_files >= 2
                    or has_expertise
                )
            ):
                medal = "silver"
            elif doc_matches > 0 or has_expertise or has_participants or ai_score >= 35:
                medal = "bronze"
            else:
                medal = "wood"

            item.quality_tier = medal
            item.ai_card_status_code = medal
            item.ai_card_status_reason = ", ".join(reasons[:6]) if reasons else "базовые сигналы"

            clean_flags = [f for f in (item.info_flags or []) if not str(f).startswith("AI статус:")]
            status_labels = {
                "gold": "золотой",
                "silver": "серебряный",
                "bronze": "бронзовый",
                "wood": "деревянный",
            }
            clean_flags.append(f"AI статус: {status_labels.get(medal, medal)}")
            item.info_flags = clean_flags

    def all_objects(self) -> List[ObjectViewItem]:
        return self._items

    @property
    def last_dynamic_enrich_at(self) -> float:
        return self._last_dynamic_enrich_at

    @property
    def dynamic_enrich_age_sec(self) -> Optional[int]:
        if not self._last_dynamic_enrich_at:
            return None
        return max(0, int(time.time() - self._last_dynamic_enrich_at))

    def get_item_by_key(self, object_key: str) -> Optional[ObjectViewItem]:
        for item in self._items:
            if item.key == object_key:
                return item
        return None

    def remove_item_by_key(self, object_key: str) -> None:
        self._items = [i for i in self._items if i.key != object_key]

    def _enrich_from_registry(self) -> None:
        """Dates and tender participants are always enriched from tender_monitor."""
        tender_items = [
            i for i in self._items
            if i.tender_id and i.registry_type and "nashdom" not in (i.sources or [])
        ]
        if tender_items:
            enrich_tender_items(self.tender_db, tender_items)

    @property
    def loaded_from_index(self) -> bool:
        return self._from_index

    @property
    def settings_summary(self) -> str:
        if self._from_index:
            meta = self.index_meta()
            cnt = meta.get("row_count", 0)
            at = meta.get("indexed_at")
            ms = meta.get("duration_ms")
            at_s = str(at)[:19] if at else "—"
            speed = f", сбор {ms} мс" if ms else ""
            return f"Индекс CRM: {cnt} объектов, обновлён {at_s}{speed}"
        if not self._settings:
            return "Индекс не построен — медленная прямая загрузка. Нажмите «Построить индекс»."
        parts = []
        if self._settings.region_ids:
            names = [self._region_names.get(rid, str(rid)) for rid in self._settings.region_ids]
            parts.append(f"регионы: {', '.join(names)}")
        return "Отбор superuser — " + ("; ".join(parts) if parts else "без ограничений по региону")

    def available_regions(self) -> List[tuple]:
        seen: Dict[int, str] = {}
        if self._region_names:
            seen.update(self._region_names)
        for item in self._items:
            if item.region_id and item.region:
                seen[item.region_id] = item.region
        return sorted(seen.items(), key=lambda x: x[1])

    def dynamic_product_groups(self, *, include_computers: bool = False) -> List[tuple[str, str]]:
        """Load active product groups from CRM DB with a safe static fallback.

        The contour should not depend on a hardcoded category list on first load:
        if CRM tables are present, we use them as the source of truth.
        """
        fallback = []
        try:
            from src.constants.product_groups import PRODUCT_GROUP_OPTIONS

            fallback = list(PRODUCT_GROUP_OPTIONS)
        except Exception:
            fallback = [
                ("flooring", "Напольные покрытия"),
                ("self_leveling_floors", "Наливные / промышленные полы"),
                ("lighting", "Светотехника"),
                ("curbstone", "Бордюрный камень"),
                ("drainage", "Водоотвод"),
                ("waterproofing", "Гидроизоляция"),
                ("composites", "Композиты"),
                ("computers", "Компьютеры / ИТ"),
            ]

        if not self.crm_db or self.crm_db.is_offline_mode():
            return [x for x in fallback if include_computers or x[0] != "computers"]

        try:
            profiled = ProfiledSearchService(self.crm_db)
            rows = profiled.product_groups()
            if rows:
                items = [(row.code, row.name) for row in rows]
                if include_computers:
                    return items
                return [x for x in items if x[0] != "computers"]
        except Exception as exc:
            logger.warning(f"dynamic_product_groups: {exc}")

        return [x for x in fallback if include_computers or x[0] != "computers"]

    @property
    def counts(self) -> dict:
        by_segment = {code: 0 for code, _ in OBJECT_SEGMENT_TABS}
        by_source = {code: 0 for code, _ in OBJECT_SOURCE_OPTIONS}
        by_tier = {code: 0 for code, _ in _tier_codes()}
        for item in self._items:
            by_segment[item.segment] = by_segment.get(item.segment, 0) + 1
            for src in item.sources:
                by_source[src] = by_source.get(src, 0) + 1
            by_tier[item.quality_tier] = by_tier.get(item.quality_tier, 0) + 1
        return {
            "total": len(self._items),
            "nashdom": sum(1 for o in self._items if "nashdom" in o.sources),
            "tenders": sum(1 for o in self._items if "nashdom" not in o.sources),
            "by_segment": by_segment,
            "by_source": by_source,
            "by_tier": by_tier,
        }


def _tier_codes():
    from src.constants.object_quality import OBJECT_QUALITY_TIERS

    return OBJECT_QUALITY_TIERS


def _text_matches(item: ObjectViewItem, q: str) -> bool:
    if q in (item.search_text or ""):
        return True
    haystack = " ".join(filter(None, [
        item.name,
        item.address,
        item.contract_number,
        item.pd_number,
        item.expertise_number,
        item.balance_holder,
        item.customer_name,
        item.customer_inn,
        item.contractor_name,
        item.contractor_inn,
        item.region,
        item.domrf_object_id,
    ])).lower()
    tokens = q.split()
    return all(t in haystack for t in tokens)


def _active_processed_rank(item: ObjectViewItem) -> int:
    """Higher rank for live/non-awarded tenders that already have processed docs."""
    if is_awarded(item):
        return 0
    if item.doc_matches or item.matched_files:
        return 3
    if item.quality_tier and item.quality_tier != "basic":
        return 2
    return 1


def _has_doc_hits(item: ObjectViewItem) -> bool:
    return bool((item.doc_matches or 0) > 0 or (item.matched_files or 0) > 0)


def _docs_in_queue(item: ObjectViewItem) -> bool:
    tier = (item.quality_tier or "").lower()
    flags = " ".join(item.info_flags or []).lower()
    return (
        tier == "expertise_pending"
        or "очеред" in flags
        or "documents in queue" in flags
        or "документы в очереди" in flags
        or "экспертиза есть" in flags
    )


def _is_procurement_eligible(item: ObjectViewItem) -> bool:
    """В закупочном контуре:
    - показываем все неразыгранные тендеры;
    - разыгранные оставляем только при подтверждённых совпадениях в документах.
    """
    if "nashdom" in (item.sources or []):
        return False
    if not is_awarded(item):
        return True
    return _has_doc_hits(item)


def _title_it_signal_score(item: ObjectViewItem) -> int:
    """Быстрый pre-AI сигнал по названию для ИТ-лотов без парсинга docs."""
    text = " ".join(
        str(x or "")
        for x in (item.name, item.search_text, item.ai_subcategory, item.ai_primary_class)
    ).lower()
    strong = (
        "ноутбук", "ноутбуков", "laptop", "системный блок", "рабочая станция",
        "моноблок", "персональный компьютер", "сервер", "мфу", "принтер",
    )
    medium = (
        "монитор", "клавиатур", "мыш", "картридж", "ssd", "оперативной памяти",
        "жестк", "сетев", "компьютерн", "ит-оборуд",
    )
    if any(token in text for token in strong):
        return 30
    if any(token in text for token in medium):
        return 18
    return 0


def _pipeline_rank(item: ObjectViewItem) -> int:
    """Business ordering for material-sales procurement queue.

    1) active/non-awarded with parsed documents and hits;
    2) awarded with parsed documents and hits, if still has sales window.
    """
    awarded = is_awarded(item)
    has_hits = _has_doc_hits(item)
    it_signal = _title_it_signal_score(item)
    if not awarded and has_hits:
        return 450 + min(40, it_signal)
    if not awarded:
        # Открытые без doc-hits остаются в выдаче, но ниже обработанных.
        return 180 + min(30, it_signal)
    if awarded and has_hits:
        return 300 + min(20, it_signal)
    return 0


def filter_objects(
    items: List[ObjectViewItem],
    *,
    segment: Optional[str] = None,
    sources: Optional[Set[str]] = None,
    search: str = "",
    status: Optional[str] = None,
    region_id: Optional[int] = None,
    quality_tier: Optional[str] = None,
    award_stage: Optional[str] = None,
) -> List[ObjectViewItem]:
    """Filter and rank CRM objects for the procurement contour."""
    result = [
        o for o in items
        if _is_procurement_eligible(o) and not is_lost_for_sales_window(o)
    ]
    if award_stage == "open":
        result = [o for o in result if not is_awarded(o)]
    elif award_stage == "awarded":
        result = [o for o in result if is_awarded(o)]
    if segment:
        result = [o for o in result if o.segment == segment]
    if sources:
        result = [o for o in result if any(s in sources for s in o.sources)]
    if region_id is not None:
        result = [o for o in result if o.region_id == region_id]
    if quality_tier:
        result = [o for o in result if o.quality_tier == quality_tier]
    if status and status != "Все":
        result = [o for o in result if (o.status or "") == status]
    if search:
        q = search.strip().lower()
        result = [o for o in result if _text_matches(o, q)]

    result.sort(
        key=lambda o: (
            -_pipeline_rank(o),
            -_title_it_signal_score(o),
            -int(o.ai_priority_score or 0),
            -int(o.doc_matches or 0),
            -int(o.matched_files or 0),
            -o.info_score,
            o.delivery_end_date or o.end_date or "9999-12-31",
            o.name or "",
        )
    )
    return result
