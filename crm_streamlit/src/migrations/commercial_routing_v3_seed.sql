-- COMMERCIAL-ROUTING-V3 seed — global OKPD priors (ONE_OKPD_ONE_CATEGORY=NO)

INSERT INTO crm_category_okpd_priors (
    commercial_category_code, okpd_pattern, match_type, prior_weight,
    active, provenance, migration_class, registry_version
) VALUES
    ('lighting', '27.40', 'PREFIX', 70, TRUE, 'SUPPLEMENTAL_EXPERT_RULE', 'MIGRATE_CONFIDENT', 3),
    ('lighting', '42.11', 'PREFIX', 35, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('waterproofing', '42.11', 'PREFIX', 30, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('drainage_water_management', '42.11', 'PREFIX', 25, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('curbstone', '42.11', 'PREFIX', 20, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('composite_structures', '42.11', 'PREFIX', 20, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('flooring', '43.33', 'PREFIX', 50, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('computers', '26.20', 'PREFIX', 80, TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('cable_support_systems', '27.32', 'PREFIX', 40, TRUE, 'SUPPLEMENTAL_EXPERT_RULE', 'REVIEW_REQUIRED', 3)
ON CONFLICT (commercial_category_code, okpd_pattern, match_type) DO UPDATE SET
    prior_weight = EXCLUDED.prior_weight,
    migration_class = EXCLUDED.migration_class,
    updated_at = NOW();

-- Default legacy stop words → NEGATIVE_SIGNAL (not HARD_EXCLUSION)
INSERT INTO crm_category_routing_signals (
    commercial_category_code, signal_type, signal_scope, phrase,
    active, provenance, migration_class, registry_version
) VALUES
    ('lighting', 'NEGATIVE_SIGNAL', 'PRELIMINARY_TITLE', 'отопление', TRUE, 'legacy_stop_default', 'MIGRATE_CONFIDENT', 3),
    ('lighting', 'POSITIVE_SIGNAL', 'PRELIMINARY_TITLE', 'светильник', TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('lighting', 'POSITIVE_SIGNAL', 'PRELIMINARY_TITLE', 'освещение', TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3),
    ('waterproofing', 'POSITIVE_SIGNAL', 'PRELIMINARY_TITLE', 'гидроизоляц', TRUE, 'routing_v3_seed', 'MIGRATE_CONFIDENT', 3)
ON CONFLICT DO NOTHING;
