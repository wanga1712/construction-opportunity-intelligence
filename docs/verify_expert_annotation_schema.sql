\pset tuples_only on
\pset format unaligned

SELECT 'OWNER|' || c.relname || '|' || pg_get_userbyid(c.relowner)
FROM pg_class c
WHERE c.relname IN (
    'crm_v3_expert_annotations',
    'crm_v3_taxonomy_proposals',
    'crm_manual_assessments_audit'
)
ORDER BY c.relname;

SELECT 'COLUMN|' || table_name || '|' || column_name || '|' || data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
      'crm_v3_expert_annotations',
      'crm_v3_taxonomy_proposals',
      'crm_manual_assessments_audit'
  )
ORDER BY table_name, ordinal_position;

SELECT 'INDEX|' || tablename || '|' || indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN (
      'crm_v3_expert_annotations',
      'crm_v3_taxonomy_proposals'
  )
ORDER BY tablename, indexname;

SELECT 'CONSTRAINT|' || conrelid::regclass::text || '|' || conname || '|' || contype::text
FROM pg_constraint
WHERE conrelid IN (
    'crm_v3_expert_annotations'::regclass,
    'crm_v3_taxonomy_proposals'::regclass
)
ORDER BY conrelid::regclass::text, conname;

SELECT 'PRIVILEGE|annotations_table|' ||
       has_table_privilege(
           'crm_app', 'crm_v3_expert_annotations', 'SELECT,INSERT,UPDATE'
       );
SELECT 'PRIVILEGE|annotations_sequence|' ||
       has_sequence_privilege(
           'crm_app', 'crm_v3_expert_annotations_id_seq', 'USAGE'
       );
SELECT 'PRIVILEGE|proposals_table|' ||
       has_table_privilege(
           'crm_app', 'crm_v3_taxonomy_proposals', 'SELECT,INSERT,UPDATE'
       );
SELECT 'PRIVILEGE|proposals_sequence|' ||
       has_sequence_privilege(
           'crm_app', 'crm_v3_taxonomy_proposals_id_seq', 'USAGE'
       );
