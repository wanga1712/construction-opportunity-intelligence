"""Primary Hydro Leads work queue; reads only the canonical CRM repository."""
from __future__ import annotations
import json
import os
from pathlib import Path
import streamlit as st
from src.services.hydro.card_projection import HydroLeadCardDTO
from src.services.hydro.lead_repository import HydroLeadRepository
from src.services.hydro.commercial_repository import HydroCommercialRepository
from src.services.hydro.commercial_hierarchy import CommercialLayer

_SHADOW_CACHE_PATH = Path(os.getenv("HYDRO_SHADOW_CACHE_PATH", "/opt/backups/hydro_phase2c_20260905/shadow_results.json"))


def _shadow_results() -> dict[str, dict]:
    try:
        payload = json.loads(_SHADOW_CACHE_PATH.read_text(encoding="utf-8"))
        return {row["entity_key"]: row["result"] for row in payload.get("records", []) if isinstance(row.get("result"), dict)}
    except (OSError, ValueError, TypeError):
        return {}

def _object_caption(card: HydroLeadCardDTO) -> str:
    if not card.top_objects: return "Объекты не загружены"
    obj = card.top_objects[0]
    return " · ".join(x for x in (obj.address, obj.cadastral_number, f"{obj.area_total:g} м²" if obj.area_total else None) if x) or "Факты объекта уточняются"

def render_lead_detail(repo: HydroLeadRepository, lead_id: int | str) -> None:
    card = repo.get_lead(lead_id)
    if not card: st.warning("Лид не найден."); return
    st.subheader(card.company_name or "УК НЕ ОПРЕДЕЛЕНА")
    st.caption(f"{card.lead_kind} · {card.state} · {card.object_count} объектов · источник: {card.source_health}")
    if card.company_inn or card.company_ogrn or card.company_phone:
        st.caption(" · ".join(x for x in (f"ИНН {card.company_inn}" if card.company_inn else None, f"ОГРН {card.company_ogrn}" if card.company_ogrn else None, card.company_phone) if x))
    if card.next_task_label: st.info(f"Следующее действие: {card.next_task_label}")
    st.write(f"Потенциал объекта: {card.potential.grade} ({card.potential.score}) · Готовность лида: {card.readiness.grade} ({card.readiness.score})")
    for obj in card.top_objects:
        with st.container(border=True):
            st.markdown(f"**{obj.address or 'Адрес не указан'}** · {obj.cadastral_number or 'кадастр не указан'}")
            st.caption(f"Площадь: {obj.area_total or '—'} · Подземных этажей: {obj.floors_underground or '—'} · Потенциал: {obj.potential.grade} ({obj.potential.score})")
            if obj.missing_facts: st.warning("Неизвестно: " + ", ".join(obj.missing_facts))

def render_hydro_leads_tab(crm_db) -> None:
    if crm_db is None:
        st.info("Карточки Hydro недоступны: canonical CRM DB не подключена."); return
    st.header("🔥 Клиенты / коммерческие слои")
    st.caption("Детерминированная коммерческая иерархия по canonical CRM snapshot; физический объект не считается самостоятельным UK-лидом.")
    commercial_repo = HydroCommercialRepository(crm_db)
    entities = commercial_repo.list_entities()
    shadow_results = _shadow_results()
    if not commercial_repo.schema_available:
        st.warning("Коммерческий Hydro read-model недоступен: canonical CRM schema не прочитана."); return
    layer_tabs = st.tabs(["🏛 Жилищник", "🏢 Другие УК", "🔎 Без УК — тип известен", "🧩 Не классифицировано"])
    layer_map = ((CommercialLayer.ZHILISHNIK, layer_tabs[0]), (CommercialLayer.OTHER_UK, layer_tabs[1]), (CommercialLayer.NO_UK_KNOWN, layer_tabs[2]), (CommercialLayer.UNKNOWN, layer_tabs[3]))
    for layer, tab in layer_map:
        with tab:
            selected = [entity for entity in entities if entity.layer == layer]
            st.caption(f"{len(selected)} коммерческих сущностей")
            if not selected:
                st.info("В этом слое canonical snapshot пока пуст.")
                continue
            for entity in selected[:100]:
                if entity.management:
                    st.subheader(entity.management.name or "Организация без названия")
                    st.caption(f"{len(entity.objects)} объектов · portfolio {entity.portfolio_score.grade} ({entity.portfolio_score.score})")
                else:
                    obj = entity.objects[0]
                    cls = entity.object_class.commercial_class.value if entity.object_class else "UNKNOWN"
                    st.subheader(cls)
                    st.caption(f"{obj.get('address') or 'Адрес уточняется'} · {obj.get('cadastral_number') or 'кадастр уточняется'}")
                    st.write(f"Технический потенциал: {(obj.get('object_potential') or {}).get('grade', '—')} · следующий канал: исследование коммерческого входа")
                shadow = shadow_results.get(entity.entity_key)
                if shadow:
                    st.info(
                        "Qwen shadow · "
                        f"{shadow['commercial_interest_grade']} ({shadow['commercial_interest_score']}) · "
                        f"канал: {shadow['recommended_channel']}\n\n"
                        + "Причины: " + "; ".join(shadow["reasons"])
                    )
                else:
                    st.info("Qwen shadow: offline assessment не запускается при рендере страницы; результат появится после batch-прогона.")
