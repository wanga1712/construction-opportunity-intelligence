"""Supplementary panels for the objects page."""
import streamlit as st

from src.constants.object_quality import OBJECT_QUALITY_TIERS, TIER_BORDER_COLORS, TIER_BADGE_COLORS, TIER_CARD_BG
from src.services.companies_service import CompaniesService
from src.services.object_ai_classifier import classify_objects_with_ai
from src.services.object_ai_scores import apply_object_ai_scores
from src.services.object_category_labels import apply_object_category_labels
from src.services.docs_soft_reclassify import soft_reclassify_docs_queue
from src.services.docs_priority_sync import sync_docs_priority_hints
from src.services.object_leads_bridge import sync_awarded_object_leads
from src.services.objects_index_manager import build_objects_index
from src.services.objects_service import ObjectsService


def render_index_panel(service: CompaniesService, objects_service: ObjectsService) -> None:
    meta = objects_service.index_meta()
    row_count = meta.get("row_count") or 0
    with st.expander("Индекс объектов в CRM", expanded=not row_count):
        if row_count:
            st.success(
                f"В индексе **{row_count}** объектов · "
                f"обновлён: {str(meta.get('indexed_at', '—'))[:19]} · "
                f"сбор: {meta.get('duration_ms', '—')} мс"
            )
            if not meta.get("source_indexes_ok"):
                st.warning("Не все индексы на сервере БД созданы — см. лог.")
        else:
            st.warning(
                "Индекс не построен. Прямая загрузка занимает 30–60 с. "
                "Нажмите «Построить индекс» — дальше список и поиск будут мгновенными."
            )
        if st.button("Построить / обновить индекс", key="objects_build_index", type="primary"):
            progress = st.progress(0.0, text="Старт…")
            status = st.empty()

            def on_progress(msg: str, pct: float) -> None:
                progress.progress(min(1.0, pct), text=msg)
                status.caption(msg)

            ok, message, _ = build_objects_index(
                service.crm_db, service.radar_db, objects_service.tender_db, on_progress=on_progress,
            )
            st.session_state.pop("objects_service", None)
            (st.success if ok else st.error)(message)
            progress.progress(1.0, text="Готово")
            st.rerun()


def render_legend() -> None:
    cols = st.columns(len(OBJECT_QUALITY_TIERS))
    for col, (code, label) in zip(cols, OBJECT_QUALITY_TIERS):
        border = TIER_BORDER_COLORS.get(code, "#CCC")
        badge_bg, badge_fg = TIER_BADGE_COLORS.get(code, ("#EEE", "#333"))
        card_bg = TIER_CARD_BG.get(code, "#FFF")
        with col:
            st.markdown(
                f'<div style="background:{card_bg};border-left:5px solid {border};'
                f'border-radius:6px;padding:8px 10px;font-size:12px;">'
                f'<span style="background:{badge_bg};color:{badge_fg};padding:2px 8px;'
                f'border-radius:999px;font-weight:700;border:1px solid {border};">'
                f'{label}</span></div>',
                unsafe_allow_html=True,
            )


def render_ai_resegment_panel(objects_service: ObjectsService) -> None:
    with st.expander("AI-пересчёт категорий объектов", expanded=False):
        st.caption(
            "Модель использует ручные исправления как эталон. "
            "Ручные метки не перетираются; остальные объекты получают AI-сегмент и AI-приоритет."
        )
        all_items = objects_service.all_objects()
        c1, c2 = st.columns([1, 2])
        with c1:
            mode = st.selectbox(
                "Объём", ["Первые 50", "Первые 200", "Все объекты"],
                index=0, key="objects_ai_resegment_limit",
            )
        limit = {"Первые 50": 50, "Первые 200": 200, "Все объекты": None}[mode]
        with c2:
            st.caption(
                f"К пересчёту: {len(all_items) if limit is None else min(limit, len(all_items))} "
                f"из {len(all_items)} объектов."
            )
        if st.button(
            "Пересчитать категории и приоритет AI", key="objects_ai_resegment_btn",
            type="primary", use_container_width=True,
        ):
            progress = st.progress(0.0, text="Старт…")
            status = st.empty()

            def on_progress(msg: str, pct: float) -> None:
                progress.progress(min(1.0, max(0.0, pct)), text=msg)
                status.caption(msg)

            result = classify_objects_with_ai(
                all_items, limit=limit, overwrite_user=False, on_progress=on_progress,
            )
            apply_object_category_labels(all_items)
            apply_object_ai_scores(all_items)
            st.session_state.pop("objects_service", None)
            st.success(
                "AI-пересчёт завершён: "
                f"обработано {result['ok']}, изменено {result['changed']}, "
                f"ручных пропущено {result['skipped_user']}, ошибок {result['failed']}."
            )
            st.rerun()


def render_leads_bridge_panel(objects_service: ObjectsService) -> None:
    with st.expander("CRM-состояние объектов", expanded=False):
        st.caption(
            "Вкладка «Объекты» остаётся основной очередью лидов. "
            "Эта операция создаёт технические записи в crm_leads для awarded-объектов, "
            "у которых до окончания поставки/исполнения не меньше 90 дней. "
            "Повторный запуск безопасен: существующие записи обновляются, дубли не плодятся."
        )
        all_items = objects_service.all_objects()
        awarded_total = sum(1 for o in all_items if "awarded" in (o.registry_type or "").lower())
        st.caption(f"В загруженной очереди awarded-объектов: {awarded_total} из {len(all_items)}.")
        if st.button(
            "Связать awarded-объекты с CRM-лидами", key="objects_sync_awarded_leads",
            type="primary", use_container_width=True,
        ):
            with st.spinner("Создаю/обновляю CRM-состояние объектов…"):
                stats = sync_awarded_object_leads(objects_service.crm_db, all_items)
            if stats.get("error"):
                st.error(stats["error"])
            else:
                st.success(
                    "Готово: "
                    f"просмотрено {stats['scanned']}, подходит {stats['eligible']}, "
                    f"создано {stats['created']}, обновлено {stats['updated']}, "
                    f"пропущено {stats['skipped']}, ошибок {stats['failed']}."
                )


def render_docs_priority_panel(objects_service: ObjectsService) -> None:
    with st.expander("AI-приоритет для docs-демонов", expanded=False):
        st.caption(
            "Синхронизирует в tender_monitor таблицу `crm_docs_priority_hints` подсказки приоритета "
            "и профиля анализа (open/awarded, segment-based profile)."
        )
        if st.button(
            "Синхронизировать AI-приоритет в очередь документов",
            key="objects_sync_docs_priority",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Публикую приоритеты в tender_monitor…"):
                stats = sync_docs_priority_hints(objects_service.tender_db, objects_service.all_objects())
            if stats.get("error"):
                st.error(stats["error"])
            else:
                st.success(
                    f"Готово: scanned={stats['scanned']} · upserted={stats['upserted']} · skipped={stats['skipped']}"
                )
        if st.button(
            "Soft reclassify open/awarded в docs-очереди",
            key="objects_soft_reclassify_docs_queue",
            use_container_width=True,
        ):
            with st.spinner("Перераскладываю pending-задачи между open/awarded…"):
                stats = soft_reclassify_docs_queue(objects_service.tender_db)
            if stats.get("error"):
                st.error(stats["error"])
            else:
                st.success(
                    "Обновлено задач: "
                    f"{stats.get('total', 0)} "
                    f"(44 o→a={stats.get('44_open_to_awarded', 0)}, "
                    f"223 o→a={stats.get('223_open_to_awarded', 0)}, "
                    f"44 a→o={stats.get('44_awarded_to_open', 0)}, "
                    f"223 a→o={stats.get('223_awarded_to_open', 0)})"
                )
