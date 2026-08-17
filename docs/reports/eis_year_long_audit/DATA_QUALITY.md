# DATA_QUALITY

No raw XML pulled off EIS in this audit (production parser left running; no extra SOAP). Evidence = tag maps + DB null rates + journal field lists.

## 44 awarded (n=64941)

| Field | non-null |
|---|---|
| contract_number, title, initial_price, tender_link, delivery start/end | 64941 / 64941 |
| okpd_id | 64932 |
| contractor_id | 58442 (90%) |
| final_price | 57278 (88%) |
| customer_id | 29901 (46%) |
| start_date/end_date (notice window) | 30608 (47%) |

Journal after 3b26815 shows awarded UPDATEs setting delivery_*, final_price, auction_name, contractor_id, okpd_id — matches RGK map (`priceInfo/price`, executionPeriod).

## 44 main (n=22030)

okpd_id 100%; end_date only 6208 (28%) — many notices missing submission close in DB.

## 223

Notices: initial_price 100%, final_price 0% (correct for notices). Awarded table empty — **recouped 223 not producing awarded rows**. Invariant maps are correct; pipeline outcome is incomplete.

## 615

317/317 have initial_price, final_price, auction_name.

## rgk_contract_unresolved

31420/31443 reason=MISSING_OKPD_ID — non-construction OKPD recorded, not inserted. Not a mapping bug; filter by design.

DATA_QUALITY_ISSUES=223 awarded empty; 44 awarded customer_id often null; 44 main end_date sparse; unresolved table growth; no XML-vs-DB byte trace this WIP.
