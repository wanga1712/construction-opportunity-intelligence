# DATA_FLOW_615PP

Enabled in config; regions allowlist default 77,50; hydro keyword filter.

| DEST | SOURCE |
|---|---|
| contract_number | commonInfo/regNum |
| tender_link | commonInfo/href |
| auction_name | purchaseSubjectInfo/name (or synthetic from work_kind_code) |
| start/end and delivery_* | financesInfo/stagesInfo/stageInfo/startDate|endDate |
| initial_price and final_price | financesInfo/price (same field) |
| customer | customerInfo/* |
| contractor | legalEntityRFInfo/* |
| work_kind_code/name | purchaseSubjectInfo/code|name |
| is_waterproofing / matched_keywords | full-tree keyword scan |
| links | printFormInfo / attachmentInfo → links_documentation_615_pp |

WRITE: `reestr_contract_615_pp` (317 rows). No OKPD in XML; okpd_id unused. CRM/AI historically selected 615 alongside 44.
