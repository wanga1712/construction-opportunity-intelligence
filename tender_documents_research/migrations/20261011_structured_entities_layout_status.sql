-- EMBEDDED column-mapping contract: how a fact's value was established.
--   CONSISTENT          value accepted (line_total OR qty*price, reconciled)
--   INCONSISTENT_LAYOUT line_total != qty*unit_price -> value = NULL (coverage gap)
--   UNSUPPORTED_LAYOUT  no recognisable header -> no value guessed

ALTER TABLE structured_entities
    ADD COLUMN IF NOT EXISTS layout_status text;

COMMENT ON COLUMN structured_entities.layout_status IS
    'CONSISTENT | INCONSISTENT_LAYOUT | UNSUPPORTED_LAYOUT (value provenance)';
