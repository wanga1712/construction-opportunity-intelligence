# DATA_FLOW_44FZ

## Notices (PRIZ)

| DEST | SOURCE_TAG | TRANSFORM |
|---|---|---|
| contract_number | purchaseNumber | text |
| tender_link | href | text |
| auction_name | purchaseObjectInfo | required; empty → delete XML, skip |
| start_date | collectingInfo/startDT | date |
| end_date | collectingInfo/endDT | submission window, not execution |
| initial_price | maxPriceInfo/maxPrice | НМЦК |
| customer (text) | customer/fullName | also customer table via INN |
| guarantee_amount | applicationGuarantee/amount | optional |
| delivery_region/address | GARInfo/* | text |
| okpd_id | OKPDCode / okpd2/code | lookup collection_codes_okpd; non-match skip |
| customer_id | responsibleOrgInfo/INN | customer insert/lookup |
| trading_platform_id | ETP/name | lookup/insert |
| region_id | SOAP region | DatabaseIDFetcher |
| links_documentation_44_fz | printFormInfo/url, attachmentInfo | INSERT per URL |

WRITE: INSERT `reestr_contract_44_fz` or UPDATE main/commission if `check_contract_in_any_table` hits.

## Recouped (RGK)

| DEST | SOURCE | TRANSFORM |
|---|---|---|
| contract_number | order/notificationNumber | identity |
| delivery_start_date | executionPeriod/startDate | last/first occurrence |
| delivery_end_date | executionPeriod/endDate | last endDate |
| final_price | priceInfo/price | actual contract price |
| auction_name | contractSubject | skip placeholder `Контракт {n}` on insert |
| okpd_id | OKPD2/code list | first code in collection_codes_okpd |
| contractor_id | EGRULInfo/INN | contractor insert/lookup |
| links | printForm/attachment url | INSERT if parent in **main** 44 table only |

WRITE: UNION lookup all 44 registries except completed → UPDATE allowed fields in **that** table (including awarded) → maybe promote to awarded → else INSERT main if okpd_id+real title else UPSERT `rgk_contract_unresolved`.

Feb 2026 path: lookup **main table only**; no awarded update; no unresolved table.
