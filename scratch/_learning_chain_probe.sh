#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
for t in crm_v3_pre_research_snapshots crm_v3_exhaustive_truth crm_v3_shadow_evaluations crm_v3_learning_examples crm_v3_raw_source_evidence; do
  printf "%-34s %s\n" "$t" "$($PSQL "select count(*) from $t" 2>/dev/null || echo 'нет таблицы')"
done
echo "--- queue rows eligible for snapshots ---"
$PSQL "select status, count(*) from document_processing_queue group by 1 order by 2 desc" 2>/dev/null | head -5
echo "--- last observer cycle counts ---"
journalctl -u crm-v3-learning-observer.service --no-pager 2>/dev/null | grep -E "cycle|snapshot|truth|eval|example" | tail -10
