"""Prompt templates and training examples for object AI classification."""
from __future__ import annotations

from src.services.ai_grounding import materials_block_for_item
from src.services.object_category_labels import (
    load_category_labels,
    segment_from_label,
)
from src.services.object_models import ObjectViewItem
from src.services.sales_spin_playbook import spin_block_for_prompt

MODEL_VERSION = "crm-object-classifier-2026-07-29-grounded"


def training_examples(limit: int = 24) -> str:
    rows = [
        row for row in load_category_labels().values()
        if row.get("source") == "user" and row.get("label")
    ]
    if not rows:
        return "Пользовательских примеров пока нет."
    lines = []
    for row in rows[-limit:]:
        lines.append(
            f"- registry={row.get('registry_type')}; label={row.get('label')}; "
            f"segment={row.get('segment') or segment_from_label(row.get('label'))}"
        )
    return "\n".join(lines)


def prompt_for_item(item: ObjectViewItem) -> str:
    materials_ctx = materials_block_for_item(item)
    groups = ", ".join(sorted(item.matched_product_groups or [])) or "нет"
    return (
        "Классифицируй и ранжируй объект CRM для объектных продаж материалов.\n"
        "Верни только строгий JSON без markdown и пояснений.\n\n"
        "ЖЁСТКОЕ ПРАВИЛО ПО ДАТАМ:\n"
        "- start_date и end_date — это только начало и окончание торгов/подачи заявок.\n"
        "- delivery_start_date и delivery_end_date — это срок поставки/исполнения работ.\n"
        "- Коммерческий шанс поставки нельзя рассчитывать по сроку торгов.\n"
        "- Если delivery_end_date неизвестна, прямо укажи, что срок исполнения не найден.\n\n"
        "Коммерческая логика:\n"
        "- direct_bid: торги ещё позволяют подготовить заявку, документы релевантны, есть подтверждённые совпадения материалов.\n"
        "- wait_contractor: торги уже прошли или почти прошли, но delivery_end_date ещё далеко; работаем через победителя/подрядчика.\n"
        "- monitor_only: срок исполнения меньше 90 дней от текущей даты или данных недостаточно; не скрывать автоматически.\n"
        "- reject: только если объект явно не относится к рабочим товарным направлениям.\n"
        "- Не утверждай, что материалы «найдены», если число совпадений в документах = 0.\n"
        "- Если объёмы материалов не найдены, не выдумывай: volume_signal='неизвестно', material_share_estimate=null.\n"
        "- Не выдумывай названия материалов (бордюр, линолеум и т.п.) из названия закупки или ОКПД.\n"
        "- Тип ОБЪЕКТА и найденные ТОВАРЫ — разные оси: школа с линолеумом = social/школа, "
        "а не road_infrastructure, даже если в смете есть асфальт/бордюр.\n"
        "- СОШ/МБОУ/школа/детсад/ГБУЗ/больница в названии или балансодержателе => "
        "segment=social, object_type по учреждению; товары не меняют тип объекта.\n\n"
        f"{spin_block_for_prompt()}\n\n"
        "В reason кратко: почему приоритет + одно предложение manager_next_step.\n"
        "Отдельно заполни manager_next_step (один конкретный шаг) и talk_track (2–4 фразы для звонка).\n"
        "По материалам: materials_found только из подтверждённого списка; "
        "volumes_found — короткие факты объёма/цены/ед. только из фрагментов сметы ниже.\n\n"
        "Иерархическая классификация:\n"
        "- primary_class: жилые объекты | социальные объекты | коммерческие объекты | промышленные объекты | транспортная инфраструктура | инженерная инфраструктура | благоустройство и городская среда | специальные объекты | прочее.\n"
        "- subcategory: образование, здравоохранение, культура, спорт, торговля, офисы, логистика, дороги, мосты, тоннели, водоотведение и т.п.\n"
        "- object_type: школа, больница, МКД, мост, дорога, тоннель, ТЦ, склад, завод и т.п.\n"
        "- object_subtype: если понятно из текста.\n"
        "- social_status: социальный | несоциальный | инфраструктурный | неизвестно.\n"
        "- work_type: новое строительство | реконструкция | капитальный ремонт | текущий ремонт | реставрация | благоустройство | содержание | проектирование | обследование | другое.\n"
        "- project_stage: экспертиза | подготовка закупки | торги объявлены | прием заявок | подведение итогов | подрядчик определён | строительство | поставка | выполнение работ | завершён | неизвестно.\n"
        "- stage_signals: список из 1-3 стадийных сигналов в порядке появления в тексте. Если в одном объекте есть проектирование, экспертиза и стройка, верни все найденные сигналы.\n"
        "- stage_primary: одна главная стадия из stage_signals, выбери наиболее позднюю подтверждённую стадию.\n"
        "- stage_reason: коротко объясни, почему выбраны именно эти стадии.\n"
        "- infrastructure_tags: несколько тегов, например мост, водоотвод, освещение, подземный паркинг, фасад, кровля, полы.\n\n"
        "Сегменты CRM (тип ОБЪЕКТА, не товар):\n"
        "- social: школы, больницы, детсады, соцобслуживание, учреждения, муниципальные/государственные здания, культурное наследие.\n"
        "- residential: МКД, многоквартирные и жилые дома, ЖК, УК.\n"
        "- commercial: коммерческие объекты и 223-ФЗ, если нет более точной инфраструктурной категории.\n"
        "- industrial: заводы, производство, склады, промышленные здания, инженерные сооружения предприятий.\n"
        "- road_infrastructure: улицы, дороги, мосты, тоннели, путепроводы, тротуары, благоустройство территорий "
        "(только если сам объект — дорога/улица/мост, а не школа с дорожными работами на участке).\n"
        "- other: нерелевантное или непонятное.\n"
        "- ЗАПРЕТ: компьютеры/ноутбуки/серверы/ИТ — это НЕ сегмент и НЕ primary_class. "
        "IT-закупки живут в отдельном контуре по ОКПД 26.20*. "
        "Не ставь segment/object_type «компьютеры» обычным стройкам и не путай поставку ПК с типом здания.\n\n"
        "Пользовательские эталонные исправления:\n"
        f"{training_examples()}\n\n"
        "Объект:\n"
        f"Название: {item.name}\n"
        f"Адрес: {item.address or ''}\n"
        f"Регион: {item.region or ''}\n"
        f"Реестр: {item.registry_type or ''}\n"
        f"Статус: {item.status or ''}\n"
        f"Балансодержатель: {item.balance_holder or ''}\n"
        f"Организатор: {item.customer_name or ''} {item.customer_inn or ''}\n"
        f"Подрядчик/победитель: {item.contractor_name or ''} {item.contractor_inn or ''}\n"
        f"Проектировщик: {item.expertise_planner or ''}\n"
        f"Технический заказчик: {item.expertise_technical_customer or ''}\n"
        f"Застройщик/девелопер по экспертизе: {item.expertise_developer or ''}\n"
        f"Номер закупки: {item.contract_number or ''}\n"
        f"Товарные группы по совпадениям: {groups}\n"
        f"{materials_ctx}\n"
        f"start_date/end_date — торги: {item.start_date or ''} - {item.end_date or ''}\n"
        f"delivery_start_date/delivery_end_date — поставка/исполнение: {item.delivery_start_date or ''} - {item.delivery_end_date or ''}\n"
        f"Текущий старый сегмент CRM: {item.segment}\n\n"
        "JSON schema: "
        '{"segment":"social|commercial|residential|industrial|road_infrastructure|other",'
        '"label":"...",'
        '"primary_class":"...",'
        '"subcategory":"...",'
        '"object_type":"...",'
        '"object_subtype":"...",'
        '"social_status":"социальный|несоциальный|инфраструктурный|неизвестно",'
        '"work_type":"...",'
        '"project_stage":"...",'
        '"stage_signals":["1) Проект найден + AI категоризация","2) Положительное заключение"],'
        '"stage_primary":"2) Положительное заключение",'
        '"stage_reason":"в тексте есть проектирование и положительное заключение экспертизы",'
        '"infrastructure_tags":["..."],'
        '"materials_found":["только из списка выше"],'
        '"volumes_found":["факт объёма/цены/ед. из фрагментов или []"],'
        '"confidence":0-100,'
        '"priority_score":0-100,'
        '"delivery_chance":"высокий|средний|низкий",'
        '"volume_signal":"крупный|средний|малый|неизвестно",'
        '"material_share_estimate":null,'
        '"sales_action":"direct_bid|wait_contractor|monitor_only|reject",'
        '"manager_next_step":"один конкретный шаг менеджеру",'
        '"talk_track":"2-4 фразы что сказать",'
        '"reason":"..."}'
    )
