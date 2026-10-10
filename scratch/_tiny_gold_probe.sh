#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
echo "--- самые дешёвые GOLD прямые поставки: баллы и компоненты ---"
$PSQL "select p.id, p.contract_number, p.initial_price, o.commercial_priority_score, o.candidate_initial_score, o.category_confidence, o.current_effective_medal, o.initial_medal_provenance from crm_procurement_category_opportunities o join crm_procurements p on p.id=o.procurement_id where o.opportunity_track='DIRECT_SUPPLY' and o.current_effective_medal='GOLD' and p.initial_price is not null order by p.initial_price asc limit 8"
echo "--- сколько GOLD дороже/дешевле порогов ---"
$PSQL "select case when p.initial_price is null or p.initial_price = 0 then 'нет НМЦК' when p.initial_price < 50000 then '<50k' when p.initial_price < 100000 then '50-100k' when p.initial_price < 200000 then '100-200k' when p.initial_price < 1000000 then '200k-1M' else '>=1M' end as bucket, count(*) from crm_procurement_category_opportunities o join crm_procurements p on p.id=o.procurement_id where o.opportunity_track='DIRECT_SUPPLY' and o.current_effective_medal='GOLD' group by 1 order by 2 desc"
echo "--- ai runner state ---"
systemctl is-enabled crm-ai-assessment-runner.timer 2>/dev/null; systemctl is-active crm-ai-assessment-runner.timer 2>/dev/null; systemctl is-active crm-ai-assessment-runner.service 2>/dev/null
echo "--- assessments applied to opportunities? ---"
$PSQL "select count(*) from crm_procurement_category_opportunities where opportunity_track='DIRECT_SUPPLY' and assessment_id is not null"
$PSQL "select status, count(*) from procurement_ai_assessments group by 1"
$PSQL "select count(*) from procurement_ai_assessments a join crm_procurement_category_opportunities o on o.procurement_id=a.procurement_id where o.opportunity_track='DIRECT_SUPPLY' and a.is_current"
