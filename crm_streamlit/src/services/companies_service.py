"""
Qt-free слой загрузки и сохранения компаний для Streamlit.
Логика совпадает с DesignersAnalyticsState (десктоп).
"""
from typing import Dict, List, Optional, Set, Tuple
from loguru import logger
from modules.crm.analytics.analytics_models import (
    AnalyticsSummary,
    DesignerAnalytics,
    DesignerObject,
)
from modules.crm.analytics.designer_analytics_matview import DesignerAnalyticsMatview
from modules.crm.analytics.designer_profile_constants import (
    CATEGORY_TO_REGISTRY,
    DEFAULT_GRADE_SORT,
    GRADE_SORT_ORDER,
    LEGAL_STATUS_ACTIVE,
    is_visible_legal_status,
)
from modules.crm.analytics.designer_profile_repository import DesignerProfileRepository
from modules.crm.analytics.designers_analytics_repository import DesignersAnalyticsRepository
from modules.crm.analytics.inn_normalize import normalize_inn
from modules.crm.analytics.company_deduplication import ProfileCleanupResult
from modules.crm.analytics.nashdom_role_resolver import (
    effective_registry,
    resolve_auto_company_category,
    resolve_auto_registry,
)
from src.services.balance_holder_store import BalanceHolderStore
from src.services.companies_balance import (
    companies_for_balance_holder,
    save_balance_holder_segment,
    unclassified_balance_holders,
)
class CompaniesService:
    """Загрузка, фильтрация и сохранение профилей компаний."""

    def __init__(self, radar_db=None, tender_db=None, crm_db=None):
        self.radar_db = radar_db
        self.tender_db = tender_db
        self.crm_db = crm_db
        self.repo = DesignersAnalyticsRepository(radar_db, tender_db)
        self.profile_repo = DesignerProfileRepository(crm_db) if crm_db else None
        self._balance_holder_store = BalanceHolderStore(crm_db) if crm_db else None
        self._matview = DesignerAnalyticsMatview(radar_db) if radar_db else None
        self._all: List[DesignerAnalytics] = []
        self._manual_inns: Set[str] = set()
        self._summary: Optional[AnalyticsSummary] = None
        self._pending_saves: Dict[str, DesignerAnalytics] = {}
        self.last_error: Optional[str] = None
        self.last_dedup_report: Optional[ProfileCleanupResult] = None
        self._list_duplicates_removed: int = 0

    @property
    def all_companies(self) -> List[DesignerAnalytics]:
        return self._all
    @property
    def summary(self) -> Optional[AnalyticsSummary]:
        return self._summary
    def load_sync(self, refresh_matview: bool = False) -> bool:
        """Синхронная загрузка (для Streamlit)."""
        self.last_error = None
        if not self.radar_db:
            self.last_error = "База Radar недоступна"
            return False
        try:
            self.repo.invalidate_cache()
            if self.profile_repo:
                self.profile_repo.invalidate_cache()
            if self._balance_holder_store:
                self._balance_holder_store.invalidate_cache()
            if refresh_matview and self._matview and self._matview.is_available():
                self._matview.refresh()
            if self.profile_repo:
                self.last_dedup_report = self.profile_repo.cleanup_duplicate_profiles()
            designers = self.repo.get_all_designers(force_reload=True)
            before = len(designers)
            self._all = self._dedupe_loaded_list(designers)
            self._list_duplicates_removed = before - len(self._all)
            self._merge_profiles()
            self._sort_all()
            self._summary = self.repo.get_summary(self._all)
            return True
        except Exception as e:
            logger.error(f"CompaniesService.load_sync: {e}", exc_info=True)
            self.last_error = str(e)
            return False
    def companies_for_registry(self, registry_key: str) -> List[DesignerAnalytics]:
        return [
            d for d in self._all
            if effective_registry(d) == registry_key
            and is_visible_legal_status(d.legal_status)
        ]

    @property
    def balance_holder_store(self) -> Optional[BalanceHolderStore]:
        return self._balance_holder_store
    def companies_for_balance_holder(
        self,
        main_tab: str,
        housing_sub: Optional[str] = None,
    ) -> List[DesignerAnalytics]:
        return companies_for_balance_holder(self, main_tab, housing_sub)

    def unclassified_balance_holders(self) -> List[DesignerAnalytics]:
        return unclassified_balance_holders(self)
    def save_balance_holder_segment(
        self,
        profile_inn: str,
        main_tab: Optional[str],
        housing_sub: Optional[str] = None,
    ) -> bool:
        return save_balance_holder_segment(self, profile_inn, main_tab, housing_sub)

    def favorite_companies(self) -> List[DesignerAnalytics]:
        return [
            d for d in self._all
            if d.is_favorite and is_visible_legal_status(d.legal_status)
        ]
    def get_company(self, inn: str) -> Optional[DesignerAnalytics]:
        canonical = normalize_inn(inn)
        if not canonical:
            return None
        return next((d for d in self._all if d.inn == canonical), None)

    @staticmethod
    def _dedupe_loaded_list(companies: List[DesignerAnalytics]) -> List[DesignerAnalytics]:
        from modules.crm.analytics.company_deduplication import dedupe_designer_list
        return dedupe_designer_list(companies)
    def get_company_objects(self, inn: str) -> List[DesignerObject]:
        """Объекты NashDom и закупки компании (по ключу Radar, не по override ИНН)."""
        company = self.get_company(inn)
        radar_inn = (company.profile_key if company and company.profile_key else inn)
        return self.repo.get_designer_objects(radar_inn)

    def save_profile_from_card(
        self,
        designer: DesignerAnalytics,
        *,
        profile_key: Optional[str] = None,
        previous_display_inn: Optional[str] = None,
    ) -> bool:
        """Сохранение с карточки: категория → реестр как в десктопе."""
        if designer.company_category:
            reg = CATEGORY_TO_REGISTRY.get(designer.company_category)
            if reg:
                designer.registry = reg
        return self.apply_company_change(
            designer,
            profile_key=profile_key,
            previous_display_inn=previous_display_inn,
        )

    def apply_company_change(
        self,
        designer: DesignerAnalytics,
        *,
        profile_key: Optional[str] = None,
        previous_display_inn: Optional[str] = None,
    ) -> bool:
        new_inn = normalize_inn(designer.inn)
        if not new_inn:
            self.last_error = "ИНН должен содержать 10 или 12 цифр"
            return False

        pk = normalize_inn(profile_key or designer.profile_key or previous_display_inn)
        if not pk:
            self.last_error = "Не удалось определить ключ профиля компании"
            return False

        lookup_inn = normalize_inn(previous_display_inn) or new_inn
        target: Optional[DesignerAnalytics] = None
        for d in self._all:
            if d.inn == lookup_inn or d.profile_key == pk:
                target = d
                break
        if not target:
            self.last_error = f"Компания с ИНН {lookup_inn} не найдена"
            return False

        for d in self._all:
            if d is not target and d.inn == new_inn:
                self.last_error = f"ИНН {new_inn} уже используется другой компанией"
                return False

        name = (designer.full_name or "").strip()
        if not name:
            self.last_error = "Укажите название компании"
            return False

        designer.inn = new_inn
        designer.full_name = name
        designer.profile_key = pk

        target.inn = new_inn
        target.full_name = name
        target.profile_key = pk
        target.company_category = designer.company_category
        target.company_grade = designer.company_grade
        target.registry = designer.registry
        target.website = designer.website
        target.legal_status = designer.legal_status or LEGAL_STATUS_ACTIVE
        target.is_favorite = designer.is_favorite
        if target.company_category or target.company_grade or target.registry:
            self._manual_inns.add(pk)

        self._sort_all()
        self._pending_saves[pk] = designer
        return self.flush_saves()

    def flush_saves(self) -> bool:
        if not self.profile_repo or not self._pending_saves:
            return True
        pending = dict(self._pending_saves)
        self._pending_saves.clear()
        ok = True
        for pk, d in pending.items():
            profile_key = d.profile_key or pk
            inn_override = None
            if normalize_inn(d.inn) != normalize_inn(profile_key):
                inn_override = d.inn
            saved = self.profile_repo.save_profile(
                inn=profile_key,
                company_category=d.company_category,
                company_grade=d.company_grade,
                full_name=d.full_name,
                inn_override=inn_override,
                registry=d.registry,
                website=d.website,
                legal_status=d.legal_status,
                is_favorite=d.is_favorite,
            )
            if not saved:
                ok = False
                logger.warning(f"Не удалось сохранить профиль {d.inn}")
        return ok

    def _merge_profiles(self) -> None:
        self._manual_inns = set()
        if not self.profile_repo or not self._all:
            self._apply_auto_segmentation()
            return
        profiles = self.profile_repo.get_all_profiles_map()
        for d in self._all:
            radar_inn = d.inn
            d.profile_key = radar_inn
            p = profiles.get(radar_inn)
            if p:
                if p.company_category or p.company_grade or p.registry:
                    self._manual_inns.add(radar_inn)
                d.website = p.website
                d.legal_status = p.legal_status or LEGAL_STATUS_ACTIVE
                d.is_favorite = p.is_favorite
                if p.company_category:
                    d.company_category = p.company_category
                if p.company_grade:
                    d.company_grade = p.company_grade
                if p.registry:
                    d.registry = p.registry
                if p.full_name:
                    d.full_name = p.full_name
                if p.inn_override:
                    override = normalize_inn(p.inn_override)
                    if override:
                        d.inn = override
            else:
                d.legal_status = LEGAL_STATUS_ACTIVE
                d.is_favorite = False
        self._apply_auto_segmentation()

    def _apply_auto_segmentation(self) -> None:
        for d in self._all:
            if d.inn in self._manual_inns:
                continue
            if not d.registry:
                auto_reg = resolve_auto_registry(d)
                if auto_reg:
                    d.registry = auto_reg
            if not d.company_category:
                auto_cat = resolve_auto_company_category(d)
                if auto_cat:
                    d.company_category = auto_cat

    @staticmethod
    def _grade_sort_key(d: DesignerAnalytics) -> int:
        g = d.company_grade
        if g in GRADE_SORT_ORDER:
            return GRADE_SORT_ORDER[g]
        return DEFAULT_GRADE_SORT

    def _sort_all(self) -> None:
        self._all.sort(
            key=lambda d: (
                not d.is_favorite,
                self._grade_sort_key(d),
                -d.total_objects,
            )
        )
