# DATABASE_OUTPUT

Read-only catalog 2026-08-17 ~15:48 MSK via tendermonitor venv. `file_names_xml` and `links_documentation_44_fz` COUNT(*) hit statement timeout (large).

| TABLE | COUNT | PURPOSE | PK | WRITE_PATH |
|---|---|---|---|---|
| reestr_contract_44_fz | 22030 | active 44 notices | id | PRIZ insert/update |
| reestr_contract_44_fz_commission_work | 3 | commission | id | migration/update |
| reestr_contract_44_fz_unclear | 346700 | lifecycle dump | id | status migration more than EIS day |
| reestr_contract_44_fz_unknown | 0 | unused now | id | — |
| reestr_contract_44_fz_awarded | 64941 | awarded 44 | id | RGK update + promoter |
| reestr_contract_44_fz_completed | 194701 | completed (RGK does not search) | id | daily migration |
| reestr_contract_223_fz | 1776 | active 223 | id | RI223 |
| reestr_contract_223_fz_commission_work | 13 | | id | |
| reestr_contract_223_fz_unclear | 14127 | | id | migration |
| reestr_contract_223_fz_awarded | 0 | **empty** | id | recouped 223 not promoting |
| reestr_contract_223_fz_completed | 0 | empty | id | |
| reestr_contract_615_pp | 317 | 615 | id | 615 parser |
| rgk_contract_unresolved | 31443 | non-insertable RGK | id | RecoupedContractSync |
| customer | 31993 | orgs | id | notices |
| contractor | 49861 | winners | id | RGK/notices |
| links_documentation_223_fz | 514600 | 223 docs | id | `.//document` |
| links_documentation_615_pp | 1329 | 615 docs | id | |
| trading_platform | 87 | ETP | id | notices |
| collection_codes_okpd | 2977 | OKPD allowlist | id | filter |
| region | 55 | | id | SOAP |

Indexes: contract_number on all registry tables (some duplicated idx names). `rgk_contract_unresolved` unique (fz_type, contract_number).

ESTIMATED_WRITES_PER_SOURCE_DAY: unknown XML volume; live 24.5 min of **one** region already ~5300 registry UPDATEs. file_names_xml is one insert per processed XML (timeout on count ⇒ millions likely).
