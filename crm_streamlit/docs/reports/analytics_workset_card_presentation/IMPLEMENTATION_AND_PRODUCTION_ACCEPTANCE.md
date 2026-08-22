# CRM V3 analytics workset and card presentation — implementation and production acceptance

## Result

WIP `CRM-V3-ANALYTICS-WORKSET-AND-CARD-PRESENTATION-CORRECTION-1` is **PASS / STOP**. Canonical baseline is `72a59926be4e1a32a949a57f72fdac94008b1838`; implementation is `69de9238fb2698cdf18f12615e24225a7db68347`; exact standalone production runtime is `94ce4f46980ad035a813d1f7790501877af4b239`.

Acceptance was captured on 2026-08-23 at 00:21 MSK. The procurement synchronizer remained live, so these counts are a timestamped production snapshot rather than constants.

## 1. Data workset correction

The Analytics Contour expert workset now uses only factual open lifecycle authority (`crm_stage=torgi`, `award_status=submission_open`, `end_date >= CURRENT_DATE`) plus filters explicitly selected by the operator. It does not require AI, scope, opportunity, medal, or manager-publication qualification. The global manager publication contract in `src/services/torgi_publication.py` is byte-for-byte unchanged from baseline; its result is batch-loaded as a secondary card badge.

Production waterfall:

| Stage | Count |
|---|---:|
| CRM stage torgi | 50,927 |
| submission_open | 19,522 |
| not expired / expert workset | 6,827 |
| current AI | 68 |
| AI valid | 68 |
| usable scope | 61 |
| current opportunity | 27 |
| visible opportunity | 27 |
| manager publication visible / old UI | 20 |

The exact dominant cause of the old count of 20 is that the manager-publication gate was incorrectly used as expert-workset admission. Of 6,827 lifecycle-valid rows, 6,759 were UNASSESSED, 7 had SCOPE_UNKNOWN, and 41 had no visible opportunity; FAILED, INCOMPLETE and MALFORMED were each 0 in this snapshot. Source composition was 5,790 rows from `reestr_contract_44_fz` and 1,037 from `reestr_contract_223_fz`.

Human-state partition on the same filtered workset is valid: ALL 6,827 = UNANNOTATED 6,827 + ANNOTATED 0 + NOT_INTERESTING 0. AI OUT_OF_PROFILE does not imply the human NOT_INTERESTING state.

Commission and awarded counts are true COUNT results, not the former LIMIT 500: 31,405 and 5,890. All three stages load bounded pages of 25 cards and show the true total and page range.

## 2. Visual card correction

Cards remain inline in the Analytics Contour. There is no open/detail/back route. The production card uses a 24 px/680-weight wrapping title, responsive icon-led amount/deadline/law facts, full dates, compact customer/region facts, translated human/AI/business statuses, optional factual commercial chips, and no raw technical line or empty/unknown labels. No authoritative product/material field exists, so no product chip is inferred.

The factual procurement action is above the compact inline section navigation and is labelled as EIS only when the hostname is factual EIS. Missing links produce an explicit state. Contract URLs remain distinct and are rendered only when a factual contract-specific URL exists. Initial rendering performs zero full document resolutions; opening Documents on one card performs exactly one and leaves all 25 cards inline.

## Real link audit

| CRM ID | Source | Tender link / rendered label | Contract link |
|---:|---|---|---|
| 1013 | reestr_contract_223_fz | `https://lk.zakupki.gov.ru/223/purchase/private/purchase/notice-info/details.html?noticeInfoId=19408302` / Закупка на ЕИС | absent |
| 8021 | reestr_contract_44_fz | `https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber=0130200002426000102` / Закупка на ЕИС | absent |
| 17390 | reestr_contract_223_fz | `https://lk.zakupki.gov.ru/223/purchase/private/purchase/notice-info/details.html?noticeInfoId=19266339` / Закупка на ЕИС | absent |
| 20254 | reestr_contract_44_fz_awarded | EIS tender, regNumber `0111300005125001028` / Закупка на ЕИС | factual `contractInfoId=108623377` |
| 20256 | reestr_contract_44_fz_awarded | EIS contract card, reestrNumber `0168500000626002101` / Закупка на ЕИС | factual `contractInfoId=111092279` |

All five procurement hrefs are non-empty and factual. No procurement URL was missing in the control set or the accepted first page.

## Verification

- Isolated S13 regression suite: **73 passed** in 1.23 s.
- Responsive/card focused suite: **14 passed**.
- Post-final-deploy real `app.py → objects_v2 → Analytics Contour → Идут торги` AppTest: **PASS**, 25 inline cards, true 6,827 total/page range, resolver 0→1, cards retained 25, source links 26 after one Documents activation, exceptions 0.
- In-app browser visual inspection of the actual production route: title/facts/status chips/source action/compact lazy navigation present; responsive fact grid and full date DOM verified.
- Runtime: exact HEAD `94ce4f46980ad035a813d1f7790501877af4b239`, service active, HTTP 200, tracked files clean (`git status --porcelain --untracked-files=no`). Host-local `.env`, `.streamlit`, logs and Python caches remain intentionally untracked.

## Non-change boundaries

No model, prompt, model input, routing, category registry, global manager publication rule, expert storage/payload, document semantics/pipeline, source parser, DDL or 615-PP behavior changed. STOP after this WIP.
