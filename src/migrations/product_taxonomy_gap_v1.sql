-- TAXONOMY GAPS V1
-- Additive/upsert only: confirmed PRODUCT subcategories + the cable_products
-- category. No DELETE, no rename, no dropping legacy taxonomy.
--
-- Apply as owner role crm_app (owner of the product taxonomy tables).

BEGIN;

SET LOCAL lock_timeout = '10s';

-- 1. new PRODUCT category: cable products ------------------------------------
INSERT INTO crm_product_categories (
    contour_code, category_code, category_name, category_kind, is_active
) VALUES (
    'procurement', 'cable_products', 'Кабельная продукция', 'PRODUCT', TRUE
)
ON CONFLICT (contour_code, category_code) DO UPDATE SET
    category_name = EXCLUDED.category_name,
    category_kind = 'PRODUCT',
    is_active = TRUE,
    updated_at = NOW();

-- 2. confirmed PRODUCT subcategories -----------------------------------------
INSERT INTO crm_product_subcategories (
    category_id, subcategory_code, subcategory_name,
    subcategory_kind, is_active, source
)
SELECT c.id, v.subcategory_code, v.subcategory_name, 'PRODUCT', TRUE, 'taxonomy_gap_v1'
FROM (VALUES
    -- computers
    ('computers', 'interactive_panels',   'Интерактивные панели'),
    ('computers', 'printing_consumables', 'Картриджи и расходные материалы для печати'),
    ('computers', 'projectors',           'Проекторы'),
    ('computers', 'computer_consumables', 'Расходные материалы для компьютерной техники'),
    ('computers', 'printing_parts',       'Комплектующие и запчасти для принтеров и МФУ'),
    ('computers', 'information_terminals','Информационные терминалы'),
    -- lighting
    ('lighting', 'generic_luminaires',    'Светильники общего назначения'),
    ('lighting', 'led_lamps',             'Светодиодные лампы и источники света'),
    -- drainage
    ('drainage_water_management', 'culvert_pipes', 'Водопропускные трубы'),
    -- cable products
    ('cable_products', 'generic_cables', 'Кабели и проводники общего назначения'),
    ('cable_products', 'power_cables',   'Силовые кабели')
) AS v(category_code, subcategory_code, subcategory_name)
JOIN crm_product_categories c ON c.category_code = v.category_code
ON CONFLICT (category_id, subcategory_code) DO UPDATE SET
    subcategory_name = EXCLUDED.subcategory_name,
    subcategory_kind = 'PRODUCT',
    is_active = TRUE,
    source = EXCLUDED.source,
    updated_at = NOW();

COMMIT;
