# Commercial portal API contract (external site <-> CRM)

Status: **PHASE 4 DELIVERED** (service + API). PHASE 5 (site wiring) blocked on
ownership - see the bottom of this file.
Source of truth for the WIP: `docs/wip/WIP_COMMERCIAL_SITE_CRM_LINK_V1.md`.

The site never talks to PostgreSQL. The site backend (Django in
`nodar-site-preview/backend`) calls this read-only API over loopback; the
database credentials stay in the API process environment.

## Transport

```text
base_url   http://127.0.0.1:8787      # CRM host S13, loopback only
auth       Authorization: Bearer $COMMERCIAL_PORTAL_API_TOKEN   (when configured)
format     application/json; charset=utf-8, Cache-Control: no-store
```

Every response is wrapped in a tenant context envelope so the later tariff
layer needs no contract change:

```json
{
  "context": {
    "organization_id": "org-1",
    "user_id": "u-7",
    "selected_categories": ["lighting"],
    "entitlements": [],
    "card_open_limit": 25,
    "entitlement_enforced": false
  },
  "data": { }
}
```

`organization_id`, `user_id`, `card_open_limit` may be sent as query parameters
or as `X-Organization-Id` / `X-User-Id` headers; `selected_categories` is sent
as repeated `category=` parameters. **No billing rule is enforced in this WIP**
(`entitlement_enforced` is always `false`); the fields exist so the site can
already log what it will be entitled to.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | liveness, no data |
| GET | `/api/v1/market/summary` | the PHASE 1 market snapshot (see below) |
| GET | `/api/v1/categories` | category list with opportunity counts |
| GET | `/api/v1/opportunities` | ranked procurement list (filters + paging) |
| GET | `/api/v1/procurements/{id}/preview` | PHASE 3 preview contract |
| GET | `/api/v1/procurements/{id}` | preview + commercial detail (card) |

### `/api/v1/market/summary`

`data.metrics` is keyed exactly like the database audit
(`scripts/commercial_market_audit.sql`), unit `DISTINCT_PROCUREMENT_ID`:
`COMMERCIAL_UNIVERSE_DISTINCT`, `OPEN_DISTINCT`, `AWARDED_FOLLOWUP_DISTINCT`,
`WITH_COMMERCE`, `WITHOUT_COMMERCE`, `DIRECT_SUPPLY`, `PROJECT_EMBEDDED`,
`CONFIRMED`, `PRELIMINARY_ONLY`, `AWARDED_DIRECT_IN_LIVE_MARKET`.
`data.invariants` repeats the acceptance checks so the site can refuse to render
an inconsistent snapshot.

### `/api/v1/opportunities`

Query parameters: `segment` (`OPEN` | `AWARDED_FOLLOWUP`), `scope_type`,
`category_code`, `medal` (`GOLD`|`SILVER`|`BRONZE`|`WOOD`),
`confirmed_only`, `with_commerce`, `region`, `q`, `limit` (<=200), `offset`.
Ranking is the stored commercial authority only: best
`current_effective_medal` first, then `current_effective_score` - no second
medal/ranking logic exists in the portal service.

### Preview contract (per procurement)

```text
identity        procurement_id, contract_number, source_table, source_id
title           auction_name
status          source_lifecycle, segment, crm_stage, award_status,
                admission_state, commercial_window_state
region          delivery_region
nmck            { value, currency }            value = crm_procurements.initial_price
execution_window tender_end_date, execution_start_at, execution_end_at
commercial_modes distinct opportunity_track values of CURRENT opportunities
best_medal      max(current_effective_medal)
categories[]    one entry per CURRENT category opportunity
```

Category entry:

| Field | Authority | Notes |
|---|---|---|
| `category_code`, `category_name`, `subcategory_code`, `subcategory_name` | `crm_product_categories` / `crm_product_subcategories` | |
| `medal`, `confirmed_medal`, `commercial_score`, `medal_authority` | `crm_procurement_category_opportunities.current_effective_medal` / `confirmed_base_medal` / `current_effective_score` / `initial_medal_provenance` | existing authority, never recomputed |
| `confirmed` | `confirmed_at IS NOT NULL` | documentary confirmation |
| `section_value` + `section_value_source` | `confirmed_category_facts.line_total_value` | `null` unless source = `CONFIRMED_CATEGORY_FACTS`; `NO_SELECT_GRANT` / `NO_CONFIRMED_FACTS` otherwise |
| `material_value` + `material_value_status` | `structured_entities.total_price_value` (`TRUSTED_PRODUCTION`) | `null` when the documentary layer has no prices |
| `materials_count`, `materials_sample`, `manufacturers_sample`, `brands_sample` | `structured_entities` | sample is bounded (12) |
| `technical_attributes_count` | `structured_attributes` | |
| `evidence_count` | `structured_entities.source_document_id` | distinct source documents |

`data.commercial.category_value_sum` is the sum of per-category
`material_value`; the project NMCK is never used as a category value
(`project_nmck_used_as_category_value: false`).

**Null rule:** a missing value is `null` in JSON and must be rendered as `—`
by the site; it is never converted to `0`, and `0` is never invented.

## Reference client for `auth.html` (after login)

```js
const CRM_PORTAL_API = 'http://127.0.0.1:8787';   // site backend proxies this

async function loadMarket(token, org, user, categories, cardOpenLimit) {
  const params = new URLSearchParams({
    organization_id: org, user_id: user, card_open_limit: String(cardOpenLimit)
  });
  (categories || []).forEach((c) => params.append('category', c));
  const response = await fetch(
    `${CRM_PORTAL_API}/api/v1/market/summary?${params}`,
    { headers: { Authorization: `Bearer ${token}` }, credentials: 'omit' }
  );
  if (!response.ok) throw new Error('CRM market service unavailable');
  const payload = await response.json();
  if (!Object.values(payload.data.invariants).every(Boolean)) {
    throw new Error('CRM market snapshot failed its invariants');
  }
  return payload.data;
}
```

## PHASE 5 blocker

`auth.html` lives in `/home/vitaliy/nodar-site-preview/` (served by
`serve.py` on `100.113.185.90:9999`, Django backend in `backend/nodar_core`).
`docs/PROJECT_OPERATING_RULES.md` - the single source of truth for hosts,
SSH identities, service identities and owners - does not name this site or its
owner, and it is not part of the CRM repository. Editing it would be an
external write by an undocumented identity:

```text
IDENTITY_AUTHORITY_MISSING (site owner / edit route for nodar-site-preview)
```

The contract above, the tenant envelope and the reference client are ready;
wiring the site needs the user's decision (who owns that file set, and whether
the CRM agent may edit it in place).
