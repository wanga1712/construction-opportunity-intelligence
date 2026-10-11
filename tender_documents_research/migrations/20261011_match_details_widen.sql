-- Contract fix: match provenance descriptor columns were too narrow and
-- production tasks failed with "value too long for type character varying(20)".
-- Descriptors are free-form; widen to text (additive, no data change).

ALTER TABLE document_match_details ALTER COLUMN term_type   TYPE text;
ALTER TABLE document_match_details ALTER COLUMN column_letter TYPE text;
ALTER TABLE document_match_details ALTER COLUMN cell_address  TYPE text;

COMMENT ON COLUMN document_match_details.term_type IS
    'free-form matcher term type; widened from varchar(20) 2026-10-11';
