# DATA_FLOW_223FZ

Invariants verified in `required_tags_223_fz.json` / `_recouped.json` (tests pin these).

## Notices (RI223)

| DEST | SOURCE | NOTE |
|---|---|---|
| contract_number | purchaseNoticeData/registrationNumber | |
| tender_link | purchaseNoticeData/urlEIS | |
| auction_name | purchaseNoticeData/name | |
| start_date | submissionStartDateTime | |
| end_date | **submissionCloseDateTime** | submission deadline, not execution |
| initial_price | initialSum | |
| placer / placer_inn | placer/mainInfo/* | 223-only columns |
| customer_* | customer/mainInfo/* | |
| links | printFormInfo/url; **.//document** url | per-XML xpath |

WRITE: INSERT/UPDATE `reestr_contract_223_fz` (+ commission if hit).

## Recouped (RD223 / contractCutted)

| DEST | SOURCE | NOTE |
|---|---|---|
| contract_number | contractData/purchaseNoticeInfo/purchaseNoticeNumber | purchase→contract |
| delivery_start_date | contractData/startExecutionDate | execution, not documentationDelivery |
| delivery_end_date | contractData/endExecutionDate | |
| final_price | **contractData/price** | never unitPrice |

`documentationDelivery` is not mapped (correct).

DATA QUALITY: `reestr_contract_223_fz_awarded` COUNT=0 and `_completed` COUNT=0. Recouped 223 is not landing in awarded. Unclear holds 14127 rows. Notices exist in main (1776) with final_price all NULL (expected for notices).
