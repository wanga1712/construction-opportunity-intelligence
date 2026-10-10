#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
$PSQL "select o.id, o.procurement_id, p.contract_number, p.initial_price, o.current_effective_medal, o.candidate_medal, o.candidate_initial_medal, o.status, o.current_effective_reason from crm_procurement_category_opportunities o join crm_procurements p on p.id=o.procurement_id where o.opportunity_track='DIRECT_SUPPLY' and o.current_effective_medal='GOLD' and (p.initial_price is null or p.initial_price < 100000)"
