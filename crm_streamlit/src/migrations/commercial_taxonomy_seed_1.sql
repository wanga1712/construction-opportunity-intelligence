-- COMMERCIAL-TAXONOMY-SCHEMA-AND-REGISTRY-1 seed data
-- Run after commercial_taxonomy_schema_and_registry_1.sql

-- ─── A. Semantic metadata on existing 14 active categories ───────────────────
UPDATE crm_product_categories SET
    semantic_type = 'COMMERCIAL_CATEGORY',
    lifecycle_state = 'ACTIVE',
    searchability_mode = 'DIRECT_SEARCHABLE',
    legacy_compat_role = 'KEEP_COMMERCIAL'
WHERE category_code IN (
    'cable_support_systems', 'composite_structures', 'computers', 'curbstone',
    'drainage_water_management', 'flooring', 'lighting', 'waterproofing'
);

UPDATE crm_product_categories SET
    semantic_type = 'CONTEXT_ONLY',
    lifecycle_state = 'ACTIVE',
    searchability_mode = 'NOT_SEARCHABLE_BY_POLICY',
    legacy_compat_role = 'CONTEXT_ONLY'
WHERE category_code IN ('bridge_road_infrastructure', 'external_utility_networks');

UPDATE crm_product_categories SET
    semantic_type = 'MATERIAL_ONLY',
    lifecycle_state = 'ACTIVE',
    searchability_mode = 'FAMILY_ONLY',
    legacy_compat_role = 'MATERIAL_ONLY'
WHERE category_code = 'composites';

UPDATE crm_product_categories SET
    semantic_type = 'LEGACY_MIXED',
    lifecycle_state = 'ACTIVE',
    searchability_mode = 'DIRECT_SEARCHABLE',
    legacy_compat_role = 'REDEFINED'
WHERE category_code IN (
    'concrete_materials', 'structural_reinforcement', 'waterproofing_concrete_repair'
);

-- ─── B. New target commercial family (DRAFT, not AI-active yet) ─────────────
INSERT INTO crm_product_categories (
    contour_code, category_code, category_name, sort_order, is_active,
    description, semantic_type, lifecycle_state, searchability_mode,
    legacy_compat_role, registry_version, updated_by
)
VALUES (
    'procurement', 'concrete_repair_materials',
    'Материалы для ремонта бетона', 95, FALSE,
    'Коммерческая семья материалов для ремонта бетона (отдельно от waterproofing).',
    'COMMERCIAL_CATEGORY', 'DRAFT', 'DIRECT_SEARCHABLE',
    NULL, 1, 'commercial_taxonomy_seed_1'
)
ON CONFLICT (contour_code, category_code) DO UPDATE SET
    category_name = EXCLUDED.category_name,
    description = EXCLUDED.description,
    semantic_type = EXCLUDED.semantic_type,
    lifecycle_state = EXCLUDED.lifecycle_state,
    searchability_mode = EXCLUDED.searchability_mode,
    updated_at = NOW();

-- Target injection subcategory under concrete_repair_materials (DRAFT)
INSERT INTO crm_product_subcategories (
    category_id, subcategory_code, subcategory_name, sort_order, is_active,
    semantic_type, searchability_mode, source
)
SELECT c.id, 'injection_materials', 'Инъекционные материалы', 10, FALSE,
       'INJECTION_MATERIALS', 'DIRECT_SEARCHABLE', 'commercial_taxonomy_seed_1'
FROM crm_product_categories c
WHERE c.contour_code = 'procurement' AND c.category_code = 'concrete_repair_materials'
ON CONFLICT (category_id, subcategory_code) DO UPDATE SET
    subcategory_name = EXCLUDED.subcategory_name,
    semantic_type = EXCLUDED.semantic_type,
    searchability_mode = EXCLUDED.searchability_mode,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

-- ─── C. Legacy compatibility map ────────────────────────────────────────────
INSERT INTO crm_category_legacy_compat (
    legacy_category_code, commercial_category_code, commercial_subcategory_code,
    material_family_code, object_context_code, application_area_code,
    work_method_codes, compat_strategy, notes, registry_version
) VALUES
    ('cable_support_systems', 'cable_support_systems', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('composite_structures', 'composite_structures', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('computers', 'computers', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('curbstone', 'curbstone', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('drainage_water_management', 'drainage_water_management', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('flooring', 'flooring', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('lighting', 'lighting', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('waterproofing', 'waterproofing', NULL, NULL, NULL, NULL, '[]', 'KEEP_COMMERCIAL', NULL, 3),
    ('bridge_road_infrastructure', NULL, NULL, NULL, 'bridge_road_infrastructure', NULL, '[]', 'CONTEXT_ONLY',
     'Object context / market segment, not standalone commercial category.', 3),
    ('external_utility_networks', NULL, NULL, NULL, 'external_utility_networks', NULL, '[]', 'CONTEXT_ONLY',
     'Object context / application area, not standalone commercial category.', 3),
    ('composites', NULL, NULL, 'composites', NULL, NULL, '[]', 'MATERIAL_ONLY',
     'Material family signal; commercial category determined by product context.', 3),
    ('concrete_materials', NULL, NULL, NULL, NULL, NULL, '[]', 'REDEFINED',
     'Legacy mixed code; term-level review required before concrete_repair_materials mapping.', 3),
    ('structural_reinforcement', NULL, NULL, NULL, NULL, NULL, '[]', 'REDEFINED',
     'Legacy mixed code; term-level review required — not auto-mapped by category name.', 3),
    ('waterproofing_concrete_repair', 'waterproofing', NULL, NULL, NULL, NULL,
     '["injection"]', 'REDEFINED',
     'Term-level split: waterproofing commercial family + injection work_method; concrete_repair only via term evidence.', 3)
ON CONFLICT (legacy_category_code) DO UPDATE SET
    commercial_category_code = EXCLUDED.commercial_category_code,
    commercial_subcategory_code = EXCLUDED.commercial_subcategory_code,
    material_family_code = EXCLUDED.material_family_code,
    object_context_code = EXCLUDED.object_context_code,
    application_area_code = EXCLUDED.application_area_code,
    work_method_codes = EXCLUDED.work_method_codes,
    compat_strategy = EXCLUDED.compat_strategy,
    notes = EXCLUDED.notes,
    registry_version = EXCLUDED.registry_version;

-- ─── D. Taxonomy dimensions (context / method / material / brand) ───────────
INSERT INTO crm_taxonomy_dimensions (
    dimension_type, dimension_code, display_name, normalized_term,
    term_semantic_type, evidence_role, registry_version
) VALUES
    ('WORK_METHOD', 'injection', 'Инъектирование', 'инъектирование', 'METHOD_TERM', 'SIGNAL_ONLY', 3),
    ('APPLICATION_AREA', 'basement', 'Подвал', 'подвал', 'APPLICATION_AREA_TERM', 'SIGNAL_ONLY', 3),
    ('APPLICATION_AREA', 'roof', 'Кровля', 'кровля', 'APPLICATION_AREA_TERM', 'SIGNAL_ONLY', 3),
    ('OBJECT_CONTEXT', 'roof', 'Кровля (объект)', 'кровля', 'OBJECT_CONTEXT_TERM', 'SIGNAL_ONLY', 3),
    ('BRAND', 'varton', 'ВАРТОН', 'вартон', 'BRAND_TERM', 'SIGNAL_ONLY', 3),
    ('MANUFACTURER', 'varton', 'ВАРТОН', 'вартон', 'MANUFACTURER_TERM', 'SIGNAL_ONLY', 3),
    ('MATERIAL_FAMILY', 'frp_gfrp', 'Стеклопластик', 'стеклопластик', 'MATERIAL_TERM', 'SIGNAL_ONLY', 3),
    ('MATERIAL_FAMILY', 'concrete_repair', 'Ремонтный состав для бетона', 'ремонтный состав для бетона',
     'PRODUCT_TERM', 'REQUIRE_CONTEXT', 3),
    ('MATERIAL_FAMILY', 'injection_resin', 'Инъекционная смола', 'инъекционная смола',
     'PRODUCT_TERM', 'REQUIRE_CONTEXT', 3)
ON CONFLICT (dimension_type, dimension_code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    normalized_term = EXCLUDED.normalized_term,
    term_semantic_type = EXCLUDED.term_semantic_type,
    evidence_role = EXCLUDED.evidence_role,
    registry_version = EXCLUDED.registry_version,
    updated_at = NOW();

-- ─── E. Required business semantic regression fixtures ──────────────────────
INSERT INTO crm_taxonomy_signal_examples (
    example_term, normalized_term, term_semantic_type, evidence_role,
    dimension_type, dimension_code, commercial_category_code, commercial_subcategory_code,
    is_commercial_category, notes, registry_version
) VALUES
    ('инъектирование', 'инъектирование', 'METHOD_TERM', 'SIGNAL_ONLY',
     'WORK_METHOD', 'injection', NULL, NULL, FALSE,
     'Work method; must not become a commercial category by itself.', 3),
    ('подвал', 'подвал', 'APPLICATION_AREA_TERM', 'SIGNAL_ONLY',
     'APPLICATION_AREA', 'basement', NULL, NULL, FALSE,
     'Application area; not a commercial category.', 3),
    ('кровля', 'кровля', 'APPLICATION_AREA_TERM', 'SIGNAL_ONLY',
     'APPLICATION_AREA', 'roof', NULL, NULL, FALSE,
     'Application area; must not auto-map to waterproofing category.', 3),
    ('ВАРТОН', 'вартон', 'BRAND_TERM', 'SIGNAL_ONLY',
     'BRAND', 'varton', NULL, NULL, FALSE,
     'Brand/manufacturer signal only.', 3),
    ('стеклопластик', 'стеклопластик', 'MATERIAL_TERM', 'SIGNAL_ONLY',
     'MATERIAL_FAMILY', 'frp_gfrp', NULL, NULL, FALSE,
     'Material family; does not prove a specific commercial category alone.', 3),
    ('ремонтный состав для бетона', 'ремонтный состав для бетона', 'PRODUCT_TERM', 'REQUIRE_CONTEXT',
     NULL, NULL, 'concrete_repair_materials', NULL, TRUE,
     'Target commercial family concrete_repair_materials.', 3),
    ('инъекционная смола', 'инъекционная смола', 'PRODUCT_TERM', 'REQUIRE_CONTEXT',
     NULL, NULL, 'concrete_repair_materials', 'injection_materials', TRUE,
     'Commercial subcategory injection_materials with work_method injection context.', 3)
ON CONFLICT (normalized_term, term_semantic_type) DO UPDATE SET
    example_term = EXCLUDED.example_term,
    evidence_role = EXCLUDED.evidence_role,
    dimension_type = EXCLUDED.dimension_type,
    dimension_code = EXCLUDED.dimension_code,
    commercial_category_code = EXCLUDED.commercial_category_code,
    commercial_subcategory_code = EXCLUDED.commercial_subcategory_code,
    is_commercial_category = EXCLUDED.is_commercial_category,
    notes = EXCLUDED.notes,
    registry_version = EXCLUDED.registry_version;

-- ─── F. Registry version bump + audit row ─────────────────────────────────
UPDATE crm_settings SET value = '3' WHERE key = 'category_registry_version';

INSERT INTO crm_category_registry_versions (
    version, registry_hash, change_description, changed_by, affected_category_codes
)
SELECT
    3,
    COALESCE((SELECT value FROM crm_settings WHERE key = 'category_registry_hash'), ''),
    'COMMERCIAL-TAXONOMY-SCHEMA-AND-REGISTRY-1: semantic roles, dimensions, legacy compat, signal examples',
    'commercial_taxonomy_seed_1',
    '["concrete_repair_materials"]'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM crm_category_registry_versions WHERE version = 3
);
