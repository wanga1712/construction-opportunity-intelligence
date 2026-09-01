-- CRM V4 Structured Product Fact Schema Closure Migration
-- Migration: crm_v4_structured_fact_schema_1b.sql
-- Additive & Idempotent Schema Migration for Value-Level Core Fact Raw Fields

ALTER TABLE structured_entities ADD COLUMN IF NOT EXISTS quantity_raw TEXT;
ALTER TABLE structured_entities ADD COLUMN IF NOT EXISTS unit_price_raw TEXT;
ALTER TABLE structured_entities ADD COLUMN IF NOT EXISTS total_price_raw TEXT;
ALTER TABLE structured_entities ADD COLUMN IF NOT EXISTS currency_raw TEXT;
