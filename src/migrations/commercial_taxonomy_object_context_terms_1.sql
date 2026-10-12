-- COMMERCIAL-TAXONOMY-OBJECT-CONTEXT-TERMS-1
-- WIP=OBJECT-TAXONOMY-CANONICAL-IMPLEMENTATION-V1
--
-- Additive only: registers the canonical OBJECT_CONTEXT / APPLICATION_AREA
-- terms that the canonical object taxonomy declares in
-- src/services/expert_object_taxonomy.py (OBJECT_CONTEXT_TERMS /
-- APPLICATION_AREA_TERMS). Existing rows are never deleted or renamed;
-- re-running is idempotent.
--
-- NOT applied by this WIP: production data must not change here.
--
-- OBJECT_CONTEXT  = environment/territory the object sits in.
-- APPLICATION_AREA = which part of the object is touched (separate axis).

INSERT INTO crm_taxonomy_dimensions (
    dimension_type, dimension_code, display_name, normalized_term,
    term_semantic_type, evidence_role, registry_version
) VALUES
    ('OBJECT_CONTEXT', 'landscaping', 'Озеленение и благоустройство территории',
     'озеленение и благоустройство территории', 'OBJECT_CONTEXT_TERM', 'SIGNAL_ONLY', 1),
    ('OBJECT_CONTEXT', 'courtyard', 'Дворовая территория',
     'дворовая территория', 'OBJECT_CONTEXT_TERM', 'SIGNAL_ONLY', 1),
    ('OBJECT_CONTEXT', 'external_territory', 'Прилегающая территория',
     'прилегающая территория', 'OBJECT_CONTEXT_TERM', 'SIGNAL_ONLY', 1),
    ('OBJECT_CONTEXT', 'parking_area', 'Парковочная зона',
     'парковочная зона', 'OBJECT_CONTEXT_TERM', 'SIGNAL_ONLY', 1),
    ('APPLICATION_AREA', 'facade', 'Фасад',
     'фасад', 'APPLICATION_AREA_TERM', 'SIGNAL_ONLY', 1)
ON CONFLICT (dimension_type, dimension_code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    normalized_term = EXCLUDED.normalized_term,
    term_semantic_type = EXCLUDED.term_semantic_type,
    evidence_role = EXCLUDED.evidence_role,
    registry_version = EXCLUDED.registry_version,
    updated_at = NOW();
