"""Сборка и обновление crm_objects_index с прогрессом в UI."""
import time
from typing import Callable, Dict, Optional, Tuple

from loguru import logger

from modules.crm.repositories.objects_index_repository import ObjectsIndexRepository
from src.services.objects_loader import load_curated_objects
from src.services.objects_mapper import items_to_index_rows

ProgressFn = Callable[[str, float], None]


def build_objects_index(
    crm_db,
    radar_db,
    tender_db,
    on_progress: Optional[ProgressFn] = None,
) -> Tuple[bool, str, Dict]:
    """
    Построить индекс объектов в CRM.
    Returns: (ok, message, meta)
    """
    def prog(msg: str, pct: float) -> None:
        if on_progress:
            on_progress(msg, pct)

    repo = ObjectsIndexRepository(crm_db)
    if not crm_db or crm_db.is_offline_mode():
        return False, "CRM БД недоступна", {}

    prog("Схема индекса CRM…", 0.02)
    if not repo.ensure_schema():
        return False, "Не удалось создать таблицу crm_objects_index", {}

    source_ok = repo.apply_source_indexes(tender_db, radar_db, on_progress=prog)

    prog("Сбор объектов из tender / expertise / NashDom…", 0.30)
    t0 = time.perf_counter()
    try:
        items, settings, region_names = load_curated_objects(radar_db, tender_db)
    except Exception as exc:
        logger.error(f"build_objects_index load: {exc}", exc_info=True)
        return False, str(exc), {}

    prog(f"Запись {len(items)} объектов в индекс…", 0.85)
    rows = items_to_index_rows(items)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    ok = repo.replace_all(
        rows,
        duration_ms=duration_ms,
        source_indexes_ok=source_ok,
        last_error=None if source_ok else "Часть индексов источников не создана",
    )
    meta = repo.get_meta()
    if not ok:
        return False, "Ошибка записи в crm_objects_index", meta

    prog("Готово", 1.0)
    sec = duration_ms / 1000
    return True, f"Индекс обновлён: {len(rows)} объектов за {sec:.1f} с", meta
