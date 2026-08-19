# GOLDEN_BAD_CASE_SNAPSHOT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`
Phase: 3 — frozen regression baseline (READ-ONLY)

**GOLDEN_CASES_TOTAL:** 67
**GOLDEN_SNAPSHOT_SHA256:** `e959ed6dd6a89d1e6adf2fc305e8ae6c12e01370957151489dbbcddb987f3d4c`

Machine-readable: `GOLDEN_BAD_CASE_SNAPSHOT.json`

## System Baseline (pre-fix)

| Metric | Count |
|---|---|
| ASSESSED_WITH_OBJECT_UNKNOWN | 123 |
| ASSESSED_WITH_PROCUREMENT_UNASSESSED | 110 |
| ASSESSED_WITH_PYTHON_CONTEXTUAL_PRIOR | 37 |
| ASSESSED_WITH_ROUTE_UNASSESSED | 110 |
| ASSESSED_WITH_SCOPE_IN_PROFILE | 79 |
| CONFIDENCE_100_COUNT | 47 |
| GOLDEN_ID_COUNT | 67 |
| ROAD_SILVER_COUNT | 17 |
| SCORE_61_COUNT | 4 |
| TORGI_ASSESSED | 120 |
| TORGI_CONFIRMED | 0 |
| TORGI_FAILED | 7 |
| TORGI_INCOMPLETE | 0 |
| TORGI_PRELIMINARY | 120 |
| TORGI_UNASSESSED | 5865 |
| TORGI_VISIBLE_TOTAL | 6018 |
| TORGI_WITHOUT_OPPORTUNITY | 5956 |
| TORGI_WITH_OPPORTUNITY | 62 |

## Group Counts in Snapshot

| Group | Count |
|---|---|
| A_suspicious_python | 16 |
| B_unassessed_visible | 19 |
| C_valid_candidate | 25 |
| D_failed_malformed | 7 |
| E_confirmed_expert | 5 |
| mandatory_included | 10 |

## Mandatory Known Bad Cases

| procurement_id | contract_number | title (truncated) | expected_post_fix |
|---|---|---|---|
| 840 | 0351100008926000151 | Выполнение работ по устройству защитных слоев на автомобильн | REQUIRES_REASSESSMENT |
| 841 | 0351100008926000150 | Выполнение работ по устройству защитных  слоев на автомобиль | REQUIRES_REASSESSMENT |
| 844 | 0351100008926000152 | Выполнение работ по устройству защитных слоев  на автомобиль | SHOULD_REMAIN_VISIBLE_VALID_AI |
| 8003 | 0318100051226000071 | Выполнение работ по содержанию искусственных сооружений на с | REQUIRES_REASSESSMENT |
| 10795 | 0318100051226000073 | Капитальный ремонт моста через р. Иль на км 54+744 автомобил | REQUIRES_REASSESSMENT |
| 13688 | 0318100051226000068 | Капитальный ремонт укрепительных (противооползневых) сооруже | REQUIRES_REASSESSMENT |
| 24926 | 0328300015726000020 | Выполнение работ по ремонту тротуара по ул. Герцена (в рамка | SHOULD_HIDE_NO_AI |
| 27983 | 0310200000326000577 | Ремонт дорожного покрытия ул. К. Маркса (от ул. Мира до клад | SHOULD_HIDE_NO_AI |
| 28111 | 0318300537426000228 | Благоустройство спортивной площадки в сквере имени В.Н. Аван | SHOULD_HIDE_NO_AI |
| 31336 | 0124600005426000100 | Выполнение работ по содержанию автомобильных дорог общего по | SHOULD_HIDE_NO_AI |

## Expected Post-Fix Distribution

- REQUIRES_REASSESSMENT: 16
- SHOULD_HIDE_NO_AI: 26
- SHOULD_REMAIN_VISIBLE_CONFIRMED: 5
- SHOULD_REMAIN_VISIBLE_VALID_AI: 20

## Notes

- Raw Qwen JSON not persisted; all model_origin labels are MODEL_UNKNOWN.
- PYTHON_CONTEXTUAL_PRIOR cases flagged REQUIRES_REASSESSMENT, not automatic HIDE.
- UNASSESSED visible cases flagged SHOULD_HIDE_NO_AI.
- Snapshot hash covers full JSON file including cases array.

```
PHASE_3=PASS
```

**Not committed** — awaiting live-vs-Git reconciliation.