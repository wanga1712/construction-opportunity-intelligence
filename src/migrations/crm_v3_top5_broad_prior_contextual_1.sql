-- Top-5 business gate: broad works OKPD priors → contextual research
-- Construction/works codes must not assert sellable materials as direct product.

UPDATE crm_category_okpd_priors
   SET prior_kind = 'CONTEXTUAL_RESEARCH_PRIOR',
       signal_role = 'CONTEXTUAL_RESEARCH'
 WHERE active = TRUE
   AND commercial_category_code IN (
        'flooring', 'waterproofing', 'lighting', 'drainage_water_management',
        'curbstone', 'composite_structures', 'cable_support_systems',
        'composite_cable_trays'
   )
   AND (
        okpd_pattern LIKE '41.%'
        OR okpd_pattern LIKE '42.%'
        OR okpd_pattern LIKE '43.%'
        OR okpd_pattern IN ('41', '42', '43', '41.2', '42.11')
   );
