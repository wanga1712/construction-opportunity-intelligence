# EIS → CRM pipeline (factual only)

Observed 2026-08-17. No speculative boxes.

| Step | Host | Entrypoint | Input | Output / table | Checkpoint | Failure / retry | Owner module | Observability |
|---|---|---|---|---|---|---|---|---|
| EIS SOAP | S7 stunnel; S13 via socat to S7 | `eis-stunnel.service` / `eis-s7-gateway-forward.service` | zakupki.gov.ru CryptoPro tunnel | `127.0.0.1:8080` | process up | stunnel/socat Restart=always/on-failure | systemd units in `eis_ingestion/systemd/` | `systemctl` / journal |
| Parser request | S7 forward or S13 backfill | `eis_requester.EISRequester.send_soap_request` | region + subsystem + documentType + `exactDate` | SOAP XML | none | Connection/Timeout: infinite backoff 5–60 min | `eis_requester.py` | journal stdout; `errors.log` |
| Parser response | same | `utils.xml_extractor.XMLParser.extract_archive_urls` | SOAP XML | archive URLs | none | RequestException other than connect/timeout is raised | `utils/xml_extractor.py` | journal |
| Download + unzip | same | `file_downloader.FileDownloader.download_files` | archive URLs | XML dirs from `[path]` | none | logged download errors | `file_downloader.py`, `archive_extractor.py`, `eis_download_fix.py` | progress bar / journal |
| Procurement parse 44 new | same | `parsing_xml.okpd_parser` → `parsing_xml.xml_parser` | XML files PRIZ | `reestr_contract_44_fz`, customer, contractor, trading_platform, `file_names_xml` | file name insert | DB errors raise; IntegrityError counted skip | `xml_parser.py`, `database_operations.py` | in-memory `utils.stats` |
| Procurement parse 223 new | same | same with RI223 tags | XML files RI223 | `reestr_contract_223_fz` + links | same | same | `required_tags/required_tags_223_fz.json` | stats keys `reestr_contract_223_fz` |
| Recouped 44/223 | same | `xml_parser_recouped_contract.AdvancedXMLParser` + `RecoupedContractSync` | RGK / RD223 XML | update existing registry / awarded; insert only with okpd_id | RGK in-process version cache | MISSING_OKPD_ID blocks placeholder insert | `recouped_contract_sync.py` | journal WARNING/INFO |
| Documentation links | same | `XMLParser.parse_links_documentation` | xpath in tags JSON | `links_documentation_44_fz` / `_223_fz` | none | IntegrityError → skip duplicate | `xml_parser.py` | stats keys; no duration timer |
| DB upsert | S7 PostgreSQL `tender_monitor` (S13 backfill uses its configured DB via `db_credintials.env`) | `DatabaseManager` | parsed fields | registry tables | commit per insert | connect: retry every 5s forever | `database_connection.py` | journal ERROR |
| Region done | parser host | `on_region_processed` → `mark_region_processed` | region code | `region_progress.json` | that JSON | callback errors logged, region still counted processed in loop | `main.py` | debug.log DEBUG |
| Source-day complete | parser host | `TenderMonitorService.run` after `process_requests` | all remaining regions | **clears** region_progress for the date; does **not** call `save_processed_date` | absence of date key in `region_progress.json` | exception aborts date; cursor already written | `orchestration/monitoring_service.py` | print/journal "успешно обработана" |
| Cursor advance | parser host | `update_config_date` **before** work | next date | `[eis] date` | config.ini | not a completion signal | `main.py` | config.ini mtime |
| S7→S13 CRM sync | S13 | `crm-procurement-sync.timer` → `scripts/run_crm_sync.py` | S7 tender_monitor READ | S13 `crm_procurements` WRITE | timer 15 min | oneshot exit status | `crm_streamlit/scripts/run_crm_sync.py` | journal of `crm-procurement-sync.service` |
| CRM visibility | S13 | `crm-streamlit.service` | `crm_procurements` | UI HTTP :8504 | none | Streamlit process | `/opt/CRM_Streamlit` | HTTP 200 |

Contour C (document processor) is **not** on this path while workers are inactive.
