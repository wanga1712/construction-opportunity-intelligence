-- PRODUCT TAXONOMY: semantic kind columns + audit mapping + new PRODUCT
-- subcategories + SUBCATEGORY_NOT_ASSIGNED normalization.
--
-- Additive and idempotent. NO DELETEs, NO renames. Legacy object-context rows
-- are kept and only re-tagged via subcategory_kind / category_kind.
-- Apply as owner role crm_app (owner of all three tables).

BEGIN;

-- Never queue behind long-lived readers: fail fast instead of blocking the
-- live contour with a pending ACCESS EXCLUSIVE lock.
SET LOCAL lock_timeout = '10s';

-- 1. additive columns ---------------------------------------------------------
ALTER TABLE crm_product_categories
    ADD COLUMN IF NOT EXISTS category_kind TEXT NOT NULL DEFAULT 'PRODUCT';

ALTER TABLE crm_product_subcategories
    ADD COLUMN IF NOT EXISTS subcategory_kind TEXT NOT NULL DEFAULT 'PRODUCT';

ALTER TABLE crm_procurement_category_opportunities
    ADD COLUMN IF NOT EXISTS commercial_subcategory_source TEXT;
ALTER TABLE crm_procurement_category_opportunities
    ADD COLUMN IF NOT EXISTS commercial_subcategory_confidence NUMERIC(5,4);

-- allowed-value guards
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'crm_product_categories_category_kind_chk') THEN
        ALTER TABLE crm_product_categories
            ADD CONSTRAINT crm_product_categories_category_kind_chk
            CHECK (category_kind IN ('PRODUCT', 'LEGACY_CONTEXT'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'crm_product_subcategories_subcategory_kind_chk') THEN
        ALTER TABLE crm_product_subcategories
            ADD CONSTRAINT crm_product_subcategories_subcategory_kind_chk
            CHECK (subcategory_kind IN ('PRODUCT', 'OBJECT_CONTEXT', 'MIXED_LEGACY'));
    END IF;
END $$;

-- 2. category_kind mapping (audit) -------------------------------------------
UPDATE crm_product_categories
   SET category_kind = 'LEGACY_CONTEXT', updated_at = NOW()
 WHERE category_code IN (
        'composite_structures', 'bridge_road_infrastructure',
        'external_utility_networks', 'concrete_materials', 'cable_support_systems')
   AND category_kind <> 'LEGACY_CONTEXT';

UPDATE crm_product_categories
   SET category_kind = 'PRODUCT', updated_at = NOW()
 WHERE category_code IN (
        'lighting', 'waterproofing', 'flooring',
        'drainage_water_management', 'composites', 'computers')
   AND category_kind <> 'PRODUCT';

-- 3. subcategory_kind mapping (audit; everything else stays default PRODUCT) --
UPDATE crm_product_subcategories s
   SET subcategory_kind = m.kind, updated_at = NOW()
  FROM (VALUES
        ('lighting','office_admin','OBJECT_CONTEXT'),
        ('lighting','industrial_warehouse','OBJECT_CONTEXT'),
        ('lighting','road_street','OBJECT_CONTEXT'),
        ('lighting','tunnel','OBJECT_CONTEXT'),
        ('lighting','park_landscape','OBJECT_CONTEXT'),
        ('lighting','facade_arch','OBJECT_CONTEXT'),
        ('lighting','housing_public','OBJECT_CONTEXT'),
        ('lighting','education','OBJECT_CONTEXT'),
        ('lighting','medical_clean','OBJECT_CONTEXT'),
        ('waterproofing','foundation_basement','OBJECT_CONTEXT'),
        ('waterproofing','parking_basement','OBJECT_CONTEXT'),
        ('waterproofing','tunnel_bridge','OBJECT_CONTEXT'),
        ('waterproofing','joints_inputs','OBJECT_CONTEXT'),
        ('bridge_road_infrastructure','bridge_walkways_stairs','OBJECT_CONTEXT'),
        ('waterproofing','membrane_roof','MIXED_LEGACY'),
        ('drainage_water_management','bridge_drainage','MIXED_LEGACY'),
        ('drainage_water_management','composite_bridge_drainage','MIXED_LEGACY'),
        ('bridge_road_infrastructure','suspended_bridge_drainage','MIXED_LEGACY'),
        ('bridge_road_infrastructure','facade_bridge_drainage','MIXED_LEGACY'),
        ('waterproofing_concrete_repair','concrete_surface_preparation','MIXED_LEGACY')
       ) AS m(category_code, subcategory_code, kind)
  JOIN crm_product_categories c ON c.category_code = m.category_code
 WHERE s.category_id = c.id
   AND s.subcategory_code = m.subcategory_code
   AND s.subcategory_kind <> m.kind;

-- 4. approved new PRODUCT subcategories ---------------------------------------
INSERT INTO crm_product_subcategories (
    category_id, subcategory_code, subcategory_name, source, sort_order,
    subcategory_kind)
SELECT c.id, v.code, v.name, 'product_taxonomy_v1', v.sort_order, 'PRODUCT'
  FROM (VALUES
        ('lighting','indoor_luminaires','Внутренние светильники',150),
        ('lighting','street_luminaires','Уличные и дорожные светильники',160),
        ('lighting','lighting_poles','Опоры освещения',170),
        ('lighting','architectural_lighting','Архитектурное и фасадное освещение',180),
        ('lighting','lighting_controls','Управление и питание освещения',190),
        ('composites','pultruded_profiles','Пултрузионные композитные профили',10),
        ('composites','frp_gratings','Композитные решётчатые настилы',20),
        ('composites','composite_guardrails','Композитные перильные ограждения',30),
        ('composites','composite_cornice_blocks','Композитные карнизные блоки',40),
        ('composites','composite_pipeline_casings','Композитные футляры трубопроводов',50),
        ('composites','composite_concrete_fiber','Композитная фибра для бетона',60),
        ('composites','composite_cable_trays','Композитные кабельные лотки',70),
        ('composites','polymer_chutes','Полимерные водоотводные лотки',80)
       ) AS v(category_code, code, name, sort_order)
  JOIN crm_product_categories c ON c.category_code = v.category_code
    ON CONFLICT (category_id, subcategory_code) DO UPDATE
       SET subcategory_name = EXCLUDED.subcategory_name,
           subcategory_kind = 'PRODUCT',
           is_active = TRUE,
           updated_at = NOW();

-- 5. normalize literal sentinel only -----------------------------------------
UPDATE crm_procurement_category_opportunities
   SET commercial_subcategory_code = NULL, updated_at = NOW()
 WHERE commercial_subcategory_code = 'SUBCATEGORY_NOT_ASSIGNED';

COMMIT;
