# CURRENT_ARCHITECTURE

Active unit: `tendermonitor-eis-parser.service` → `/opt/tendermonitor/main.py` (not stopped during audit).

```
SOAP getDocsIP (stunnel :8080)
  → archive URLs
  → download + unzip
  → process_okpd_files
       ├─ PRIZ/223 notices: OKPD filter → XMLParser.parse_xml_tags → INSERT/UPDATE main
       ├─ RGK recouped: AdvancedXMLParser → RecoupedContractSync
       └─ 615: parse_reestr_contract_615_pp (MSK/MO allowlist + hydro keywords)
  → mark_region_processed (only after all subsystems for that region)
```

Completion: `process_requests` returns + `clear_region_progress_for_date`. `[eis] date` is a cursor written **before** work. `save_processed_date` dead.

Serial: one region, one subsystem, one archive, one XML. `time.sleep(0.5)` between SOAP document types.

Connection reuse (3b26815): one parser per folder. Remaining churn: `check_contract_in_any_table` constructs a **new** `ContractRegistryLocator()` → new `DatabaseManager()` per notice XML.
