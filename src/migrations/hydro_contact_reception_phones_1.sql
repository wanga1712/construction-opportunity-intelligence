-- CRM-HYDRO-UK-CONTACT-SCHEMA-PRODUCTION-MIGRATION-1.
-- Additive only: no existing contact rows or phone values are changed.
BEGIN;

ALTER TABLE company_contacts
    ADD COLUMN IF NOT EXISTS reception_type varchar(30),
    ADD COLUMN IF NOT EXISTS reception_schedule jsonb,
    ADD COLUMN IF NOT EXISTS reception_note text;

-- Required as the referenced key for the company-scoped composite contact FK.
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_contacts_id_company
    ON company_contacts(id, company_id);

CREATE TABLE IF NOT EXISTS company_contact_phones (
    id bigserial PRIMARY KEY,
    company_id integer NOT NULL,
    contact_id integer NULL,
    phone varchar(50) NOT NULL,
    phone_type varchar(30),
    extension varchar(20),
    label varchar(100),
    is_primary boolean DEFAULT false,
    comment text,
    created_at timestamptz DEFAULT now(),
    CONSTRAINT company_contact_phones_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES management_companies(id) ON DELETE CASCADE,
    CONSTRAINT company_contact_phones_contact_company_fkey
        FOREIGN KEY (contact_id, company_id)
        REFERENCES company_contacts(id, company_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_company_contact_phones_company
    ON company_contact_phones(company_id);
CREATE INDEX IF NOT EXISTS idx_company_contact_phones_contact
    ON company_contact_phones(contact_id);

COMMIT;
