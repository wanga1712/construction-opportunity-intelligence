# WIP: CRM-HYDRO-UK-CONTACT-SCHEMA-PRODUCTION-MIGRATION-1

## RESULT (2026-11-16)

STATUS: PASS
WIP_RESULT=PASS

PRODUCTION_MIGRATION_APPROVED=YES (explicit user decision)
MIGRATION_FILE=src/migrations/hydro_contact_reception_phones_1.sql
MIGRATION_SHA256=6f6a9a4c14780efde120e81dd48b70a98e9039e7e42ba27ff02e8db693f4454b

### Pre-migration gate

The exact SQL was inspected. The draft's existing-phone backfill was removed,
and the phone/contact relation was changed to a company-scoped composite FK.
An additive unique index on `(company_contacts.id, company_id)` supports the
referenced composite key. `contact_id` remains nullable for general company
phones. Contact deletion cascades only to its phone rows; company deletion
cascades to company phones.

DESTRUCTIVE_DDL=NO
EXISTING_DATA_UPDATE=NO
DROP_COLUMN=NO
DROP_TABLE=NO
COLUMN_RENAME=NO
TABLE_RENAME=NO
IDEMPOTENT=YES
PHONE2_PHONE3_PHONE4=NO
BACKFILL=NO

Expected additive fields: `company_contacts.reception_type`,
`company_contacts.reception_schedule`, `company_contacts.reception_note`.
New relation: `company_contact_phones`. No role CHECK was added.

### Approved production route and baseline

DB_NAME=crm
DB_HOST=S13 local PostgreSQL socket (no network address used)
DB_ROLE=postgres (approved `ssh s13` then `sudo -n -u postgres psql -d crm` route)
TABLE_OWNER=crm_app (verified from `pg_catalog`; not changed)
CONTACT_ROWS_BEFORE=0
PHONE_TABLE_BEFORE=ABSENT

The baseline query ran in a read-only transaction. It returned
`current_database()=crm`, `current_user=postgres`, contact count 0, and owner
`crm_app` for `company_contacts` and `management_companies`.

FIRST_RUN=PASS
SECOND_RUN=PASS
IDEMPOTENCY=PASS (second run skipped existing columns/table/indexes and committed)
POST_MIGRATION_SCHEMA_ACCEPTANCE=PASS
SMOKE_TEST=PASS (all test rows rolled back)
CONTACT_ROWS_AFTER=0
TEST_DATA_PERSISTED=NO
PRODUCTION_SCHEMA_MUTATED=YES
PRODUCTION_DATA_MUTATED=NO
OVERLAY_DEPLOYED=NO
CRM_RESTARTED=NO
CONTACT_RECEPTION_TYPE_EXISTS=YES
CONTACT_RECEPTION_SCHEDULE_EXISTS=YES
CONTACT_RECEPTION_NOTE_EXISTS=YES
PHONE_TABLE_EXISTS=YES
PHONE_COMPANY_FK=YES
PHONE_CONTACT_FK=YES
PHONE_COMPANY_CONTACT_INVARIANT=YES
REQUIRED_INDEXES_EXIST=YES
FIRST_RUN=PASS
SECOND_RUN=PASS
IDEMPOTENCY=PASS
SMOKE_CONTACT_RECEPTION=PASS
SMOKE_MULTIPLE_PHONES=PASS
SMOKE_COMPANY_PHONE=PASS
SMOKE_CROSS_COMPANY_REJECTED=PASS
SMOKE_CONTACT_DELETE_POLICY=PASS
SMOKE_EXISTING_READS=PASS
PHONE_ROWS_AFTER=0
EXISTING_PHONE_VALUES=UNTOUCHED (0 contact rows existed before migration)
PHONE_COLUMNS=id bigint PK; company_id integer NOT NULL; contact_id integer NULL; phone varchar(50) NOT NULL; phone_type varchar(30); extension varchar(20); label varchar(100); is_primary boolean DEFAULT false; comment text; created_at timestamptz DEFAULT now()
CONTACT_ROLE_CHECK=NO
SEQUENCES_UNCHANGED=YES (company_contacts_id_seq 4/true; company_contact_phones_id_seq 1/false)
CRM_APP_TABLE_PRIVS=true,true,true,true
CRM_APP_SEQUENCE_PRIVS=true,true
TESTS=read-only catalog acceptance; migration first/second run; rollback smoke test
SOURCE_GAPS=none for approved contact reception and phone schema
NEXT_WIP_RECOMMENDATION=WIP_CRM_HYDRO_UK_OVERLAY_FOUR_TAB_DEPLOYMENT_1
COMMITS=NONE
