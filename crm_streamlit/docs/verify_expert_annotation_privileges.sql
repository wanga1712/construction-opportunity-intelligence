SELECT
    has_table_privilege(
        'crm_app', 'crm_v3_expert_annotations', 'SELECT,INSERT,UPDATE'
    ) AS annotations_table_ok,
    has_sequence_privilege(
        'crm_app', 'crm_v3_expert_annotations_id_seq', 'USAGE'
    ) AS annotations_sequence_ok,
    has_table_privilege(
        'crm_app', 'crm_v3_taxonomy_proposals', 'SELECT,INSERT,UPDATE'
    ) AS proposals_table_ok,
    has_sequence_privilege(
        'crm_app', 'crm_v3_taxonomy_proposals_id_seq', 'USAGE'
    ) AS proposals_sequence_ok;
