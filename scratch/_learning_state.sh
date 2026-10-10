#!/bin/bash
PSQL="sudo -n -u postgres psql -d crm -Atc"
PSQLD="sudo -n -u postgres psql -d document_intelligence -Atc"
echo "--- units ---"
for u in crm-v3-learning-observer.service crm-v3-learning-dataset.service crm-v3-learning-dataset.timer crm-v3-factual-feeder.service; do
  printf "%-42s enabled=%s active=%s\n" "$u" "$(systemctl is-enabled $u 2>/dev/null)" "$(systemctl is-active $u 2>/dev/null)"
done
echo "--- tables with learning data ---"
$PSQL "select 'learning_observations', count(*) from learning_observations" 2>/dev/null || echo "learning_observations: нет таблицы в crm"
$PSQL "select 'crm_manual_assessments_audit', count(*) from crm_manual_assessments_audit"
$PSQLD "select 'category_phrase_candidates', count(*), status from category_phrase_candidates group by 2" 2>/dev/null
echo "--- learning observer last logs ---"
journalctl -u crm-v3-learning-observer.service --no-pager 2>/dev/null | tail -6
echo "--- dataset timer ---"
systemctl list-timers crm-v3-learning-dataset.timer --no-legend --plain 2>/dev/null
