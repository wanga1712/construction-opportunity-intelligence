-- Актуальные профили поиска документации, 2026-07-23.
-- Безопасный повторный запуск: старые default_* профили переименовываются,
-- группы и связи обновляются через ON CONFLICT.

INSERT INTO crm_product_groups (code, name, description)
VALUES
    ('flooring', 'Напольные покрытия', 'Линолеум, ПВХ-плитка, ковролин, спортивные и другие напольные покрытия.'),
    ('self_leveling_floors', 'Наливные / промышленные полы', 'Наливные, промышленные, эпоксидные, полиуретановые и полимерные покрытия пола.'),
    ('lighting', 'Светотехника', 'Внутреннее и наружное освещение, светильники, опоры, LED.'),
    ('curbstone', 'Бордюрный камень', 'Бордюр, бортовой камень, благоустройство улиц и дорог.'),
    ('drainage', 'Водоотводные системы', 'Лотки, дождеприёмники, дренаж, водоотведение.'),
    ('waterproofing', 'Гидроизоляция', 'Подвалы, паркинги, подземные этажи, протечки, гидроизоляционные работы.'),
    ('composites', 'Композиты', 'Композитные настилы, стеклопластик, перила, ограждения, мосты и путепроводы.'),
    ('computers', 'Компьютеры и ИТ-оборудование', 'Ноутбуки, ПК, моноблоки, серверы, периферия, анализ ТЗ и рыночных конфигураций.')
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_at = NOW();

UPDATE crm_search_profiles
SET code = 'materials_flooring',
    name = 'Материалы / напольные покрытия',
    description = 'Строительные объекты: жилые и коммерческие карточки, поиск напольных покрытий в документации.',
    updated_at = NOW()
WHERE code = 'default_flooring';

UPDATE crm_search_profiles
SET code = 'standardpark',
    name = 'Стандартпарк',
    description = 'Водоотвод, бордюрный камень, элементы благоустройства и гидроизоляционный контур по объектам.',
    updated_at = NOW()
WHERE code = 'default_multi_materials';

UPDATE crm_search_profiles
SET code = 'computers',
    name = 'Компьютеры / ИТ',
    description = 'Отдельный контур закупок компьютеров и ИТ: чтение ТЗ, параметры, бюджет, рыночная исполнимость.',
    updated_at = NOW()
WHERE code = 'default_computers';

INSERT INTO crm_search_profiles (code, name, description)
VALUES
    ('materials_flooring', 'Материалы / напольные покрытия', 'Строительные объекты: жилые и коммерческие карточки, поиск напольных покрытий в документации.'),
    ('self_leveling_floors', 'Наливные / промышленные полы', 'Отдельный профиль по промышленным и наливным полам: производства, склады, паркинги, техпомещения, общественные здания.'),
    ('waterproofing_buildings', 'Гидроизоляция / строительные объекты', 'Первый пользователь: гидроизоляция на зданиях, подземных частях, паркингах, подвалах, фундаментах и кровле.'),
    ('lighting', 'Светотехника', 'Дороги, тоннели, улицы, жилые и коммерческие объекты; светильники, опоры, LED и наружное освещение.'),
    ('composites', 'Композиты', 'Мосты, путепроводы, эстакады; композитные настилы, перила, ограждения, стеклопластик.'),
    ('standardpark', 'Стандартпарк', 'Водоотвод, бордюрный камень, элементы благоустройства и гидроизоляционный контур по объектам.'),
    ('computers', 'Компьютеры / ИТ', 'Отдельный контур закупок компьютеров и ИТ: чтение ТЗ, параметры, бюджет, рыночная исполнимость.')
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    is_active = TRUE,
    updated_at = NOW();

UPDATE crm_search_profile_groups
SET is_active = FALSE,
    priority_weight = 100
WHERE search_profile_id IN (
    SELECT id FROM crm_search_profiles
    WHERE code IN ('materials_flooring', 'self_leveling_floors', 'waterproofing_buildings', 'lighting', 'composites', 'standardpark', 'computers')
);

INSERT INTO crm_search_profile_groups (search_profile_id, product_group_id, is_active, priority_weight)
SELECT sp.id, pg.id, TRUE, 100
FROM crm_search_profiles sp
JOIN crm_product_groups pg ON (
    (sp.code = 'materials_flooring' AND pg.code = 'flooring')
    OR (sp.code = 'self_leveling_floors' AND pg.code = 'self_leveling_floors')
    OR (sp.code = 'waterproofing_buildings' AND pg.code = 'waterproofing')
    OR (sp.code = 'lighting' AND pg.code = 'lighting')
    OR (sp.code = 'composites' AND pg.code = 'composites')
    OR (sp.code = 'standardpark' AND pg.code IN ('drainage', 'curbstone', 'waterproofing'))
    OR (sp.code = 'computers' AND pg.code = 'computers')
)
ON CONFLICT (search_profile_id, product_group_id) DO UPDATE
SET
    is_active = TRUE,
    priority_weight = EXCLUDED.priority_weight;
