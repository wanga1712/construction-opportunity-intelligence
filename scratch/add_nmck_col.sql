ALTER TABLE document_processing_queue
ADD COLUMN IF NOT EXISTS normalized_nmck_rub NUMERIC;
