--
-- PostgreSQL database dump
--

\restrict pFVipabe39KqBFMug7fEDnkEAimlwf9CPXpGElCVhRwv9iS1jnx4kvKReyS91xH

-- Dumped from database version 17.7 (Ubuntu 17.7-3.pgdg24.04+1)
-- Dumped by pg_dump version 18.2 (Ubuntu 18.2-1.pgdg24.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: category_object_applicability; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.category_object_applicability (
    id bigint NOT NULL,
    category_code text NOT NULL,
    subcategory_code text DEFAULT ''::text NOT NULL,
    object_class text DEFAULT ''::text NOT NULL,
    object_type text DEFAULT ''::text NOT NULL,
    work_type text DEFAULT ''::text NOT NULL,
    base_priority integer DEFAULT 50 NOT NULL,
    processing_mode text DEFAULT 'candidate_search'::text NOT NULL,
    min_anchor_score integer DEFAULT 35 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    rules_version text DEFAULT 'v1'::text NOT NULL,
    notes text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.category_object_applicability OWNER TO postgres;

--
-- Name: category_object_applicability_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.category_object_applicability_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.category_object_applicability_id_seq OWNER TO postgres;

--
-- Name: category_object_applicability_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.category_object_applicability_id_seq OWNED BY public.category_object_applicability.id;


--
-- Name: category_object_observations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.category_object_observations (
    id bigint NOT NULL,
    category_code text NOT NULL,
    subcategory_code text DEFAULT ''::text NOT NULL,
    object_class text DEFAULT ''::text NOT NULL,
    object_type text DEFAULT ''::text NOT NULL,
    work_type text DEFAULT ''::text NOT NULL,
    document_id bigint,
    object_id bigint,
    tender_id bigint,
    registry_type text,
    match_strength integer DEFAULT 0 NOT NULL,
    evidence_count integer DEFAULT 0 NOT NULL,
    quantity_found text,
    technical_attributes_found jsonb DEFAULT '[]'::jsonb NOT NULL,
    ai_confidence numeric(5,4),
    manager_status text DEFAULT 'unreviewed'::text NOT NULL,
    observation_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.category_object_observations OWNER TO postgres;

--
-- Name: category_object_observations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.category_object_observations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.category_object_observations_id_seq OWNER TO postgres;

--
-- Name: category_object_observations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.category_object_observations_id_seq OWNED BY public.category_object_observations.id;


--
-- Name: category_object_priority_stats; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.category_object_priority_stats (
    category_code text NOT NULL,
    subcategory_code text DEFAULT ''::text NOT NULL,
    object_class text DEFAULT ''::text NOT NULL,
    object_type text DEFAULT ''::text NOT NULL,
    work_type text DEFAULT ''::text NOT NULL,
    base_priority integer DEFAULT 50 NOT NULL,
    observed_precision numeric(6,4) DEFAULT 0 NOT NULL,
    observed_frequency numeric(10,4) DEFAULT 0 NOT NULL,
    manager_confirmation_rate numeric(6,4) DEFAULT 0 NOT NULL,
    sample_size integer DEFAULT 0 NOT NULL,
    suggested_adjustment integer DEFAULT 0 NOT NULL,
    effective_priority integer DEFAULT 50 NOT NULL,
    auto_apply_allowed boolean DEFAULT false NOT NULL,
    last_recalculated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.category_object_priority_stats OWNER TO postgres;

--
-- Name: crm_activities; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_activities (
    id integer NOT NULL,
    entity_type character varying(30) NOT NULL,
    entity_id integer NOT NULL,
    activity_type character varying(50) NOT NULL,
    actor_id integer,
    payload jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_activities OWNER TO postgres;

--
-- Name: crm_activities_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_activities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_activities_id_seq OWNER TO postgres;

--
-- Name: crm_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_activities_id_seq OWNED BY public.crm_activities.id;


--
-- Name: crm_ai_training_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_ai_training_events (
    id bigint NOT NULL,
    object_key text,
    registry_type text,
    tender_id bigint,
    search_profile_id bigint,
    product_group_id bigint,
    event_type text NOT NULL,
    old_value jsonb,
    new_value jsonb,
    comment text,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_ai_training_events OWNER TO postgres;

--
-- Name: crm_ai_training_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_ai_training_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_ai_training_events_id_seq OWNER TO postgres;

--
-- Name: crm_ai_training_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_ai_training_events_id_seq OWNED BY public.crm_ai_training_events.id;


--
-- Name: crm_computer_tz_cards; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_computer_tz_cards (
    object_key text NOT NULL,
    tender_id integer,
    registry_type text,
    contract_number text,
    okpd_code text,
    status text DEFAULT 'pending'::text NOT NULL,
    tz_file_names jsonb,
    tz_text_excerpt text,
    supplier_card jsonb,
    model_name text,
    model_version text,
    error_message text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_computer_tz_cards OWNER TO postgres;

--
-- Name: crm_computer_tz_items; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_computer_tz_items (
    id bigint NOT NULL,
    object_key text NOT NULL,
    tender_id integer,
    registry_type text,
    category text NOT NULL,
    item_name text,
    qty numeric,
    unit text,
    specs jsonb DEFAULT '[]'::jsonb NOT NULL,
    source text DEFAULT 'ai'::text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_computer_tz_items OWNER TO postgres;

--
-- Name: crm_computer_tz_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_computer_tz_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_computer_tz_items_id_seq OWNER TO postgres;

--
-- Name: crm_computer_tz_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_computer_tz_items_id_seq OWNED BY public.crm_computer_tz_items.id;


--
-- Name: crm_external_entities; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_external_entities (
    id integer NOT NULL,
    source_type character varying(50) NOT NULL,
    source_key character varying(255) NOT NULL,
    payload jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_external_entities OWNER TO postgres;

--
-- Name: crm_external_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_external_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_external_entities_id_seq OWNER TO postgres;

--
-- Name: crm_external_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_external_entities_id_seq OWNED BY public.crm_external_entities.id;


--
-- Name: crm_lead_conversions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_lead_conversions (
    id integer NOT NULL,
    lead_id integer NOT NULL,
    opportunity_id integer NOT NULL,
    target_pipeline_id integer NOT NULL,
    converted_by integer,
    converted_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_lead_conversions OWNER TO postgres;

--
-- Name: crm_lead_conversions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_lead_conversions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_lead_conversions_id_seq OWNER TO postgres;

--
-- Name: crm_lead_conversions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_lead_conversions_id_seq OWNED BY public.crm_lead_conversions.id;


--
-- Name: crm_lead_disposition_reasons; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_lead_disposition_reasons (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(255) NOT NULL
);


ALTER TABLE public.crm_lead_disposition_reasons OWNER TO postgres;

--
-- Name: crm_lead_disposition_reasons_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_lead_disposition_reasons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_lead_disposition_reasons_id_seq OWNER TO postgres;

--
-- Name: crm_lead_disposition_reasons_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_lead_disposition_reasons_id_seq OWNED BY public.crm_lead_disposition_reasons.id;


--
-- Name: crm_lead_dispositions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_lead_dispositions (
    id integer NOT NULL,
    lead_id integer NOT NULL,
    reason_id integer NOT NULL,
    comment text,
    discarded_by integer,
    discarded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_lead_dispositions OWNER TO postgres;

--
-- Name: crm_lead_dispositions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_lead_dispositions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_lead_dispositions_id_seq OWNER TO postgres;

--
-- Name: crm_lead_dispositions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_lead_dispositions_id_seq OWNED BY public.crm_lead_dispositions.id;


--
-- Name: crm_lead_inbox_stages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_lead_inbox_stages (
    id integer NOT NULL,
    stage_key character varying(30) NOT NULL,
    name character varying(100) NOT NULL,
    stage_order integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.crm_lead_inbox_stages OWNER TO postgres;

--
-- Name: crm_lead_inbox_stages_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_lead_inbox_stages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_lead_inbox_stages_id_seq OWNER TO postgres;

--
-- Name: crm_lead_inbox_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_lead_inbox_stages_id_seq OWNED BY public.crm_lead_inbox_stages.id;


--
-- Name: crm_lead_routing_rules; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_lead_routing_rules (
    id integer NOT NULL,
    source_type character varying(50),
    region_pattern character varying(255),
    score_min integer DEFAULT 0,
    pipeline_id integer NOT NULL,
    priority integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.crm_lead_routing_rules OWNER TO postgres;

--
-- Name: crm_lead_routing_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_lead_routing_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_lead_routing_rules_id_seq OWNER TO postgres;

--
-- Name: crm_lead_routing_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_lead_routing_rules_id_seq OWNED BY public.crm_lead_routing_rules.id;


--
-- Name: crm_leads; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_leads (
    id integer NOT NULL,
    external_entity_id integer,
    pipeline_id integer NOT NULL,
    inbox_stage_id integer NOT NULL,
    title character varying(500) NOT NULL,
    disposition_status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    score integer DEFAULT 0 NOT NULL,
    score_breakdown jsonb,
    probability numeric(5,2),
    expected_amount numeric(15,2),
    owner_id integer,
    region character varying(255),
    tags jsonb,
    recommended_pipeline_id integer,
    source_object_id character varying(255),
    developer_name character varying(500),
    city character varying(255),
    parking_spaces integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_leads OWNER TO postgres;

--
-- Name: crm_leads_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_leads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_leads_id_seq OWNER TO postgres;

--
-- Name: crm_leads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_leads_id_seq OWNED BY public.crm_leads.id;


--
-- Name: crm_object_ai_classifications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_object_ai_classifications (
    id bigint NOT NULL,
    object_key text NOT NULL,
    tender_id bigint,
    registry_type text,
    contract_number text,
    expertise_number text,
    segment text,
    label text,
    primary_class text,
    subcategory text,
    object_type text,
    object_subtype text,
    social_status text,
    work_type text,
    project_stage text,
    infrastructure_tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    priority_score integer DEFAULT 0 NOT NULL,
    delivery_chance text,
    volume_signal text,
    sales_action text,
    model_name text,
    model_version text,
    classification_confidence integer DEFAULT 0 NOT NULL,
    classification_reason text,
    manager_corrected boolean DEFAULT false NOT NULL,
    manager_correction jsonb,
    source text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    manager_next_step text,
    talk_track text
);


ALTER TABLE public.crm_object_ai_classifications OWNER TO postgres;

--
-- Name: crm_object_ai_classifications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_object_ai_classifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_object_ai_classifications_id_seq OWNER TO postgres;

--
-- Name: crm_object_ai_classifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_object_ai_classifications_id_seq OWNED BY public.crm_object_ai_classifications.id;


--
-- Name: crm_object_profile_decisions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_object_profile_decisions (
    id bigint NOT NULL,
    object_key text NOT NULL,
    registry_type text,
    tender_id bigint,
    source_type text,
    search_profile_id bigint,
    product_group_id bigint,
    decision text NOT NULL,
    priority_score integer DEFAULT 0 NOT NULL,
    reason text,
    matched_terms jsonb DEFAULT '[]'::jsonb NOT NULL,
    rejected_terms jsonb DEFAULT '[]'::jsonb NOT NULL,
    ai_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    ai_model text,
    decided_by text DEFAULT 'system'::text NOT NULL,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT crm_object_profile_decisions_decision_check CHECK ((decision = ANY (ARRAY['global_reject'::text, 'profile_reject'::text, 'profile_keep'::text, 'profile_review'::text, 'needs_documents'::text, 'documents_queued'::text, 'documents_parsed'::text, 'qualified_lead'::text, 'in_work'::text, 'archived'::text]))),
    CONSTRAINT crm_object_profile_decisions_priority_score_check CHECK (((priority_score >= 0) AND (priority_score <= 100)))
);


ALTER TABLE public.crm_object_profile_decisions OWNER TO postgres;

--
-- Name: crm_object_profile_decisions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_object_profile_decisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_object_profile_decisions_id_seq OWNER TO postgres;

--
-- Name: crm_object_profile_decisions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_object_profile_decisions_id_seq OWNED BY public.crm_object_profile_decisions.id;


--
-- Name: crm_object_subcategory_links; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_object_subcategory_links (
    id bigint NOT NULL,
    object_key text NOT NULL,
    tender_id bigint,
    registry_type text,
    contour_code text NOT NULL,
    category_code text NOT NULL,
    subcategory_code text NOT NULL,
    confidence integer DEFAULT 0 NOT NULL,
    matched_phrases jsonb DEFAULT '[]'::jsonb NOT NULL,
    matched_products jsonb DEFAULT '[]'::jsonb NOT NULL,
    matched_brands jsonb DEFAULT '[]'::jsonb NOT NULL,
    source text DEFAULT 'docs_fact'::text NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_object_subcategory_links OWNER TO postgres;

--
-- Name: crm_object_subcategory_links_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_object_subcategory_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_object_subcategory_links_id_seq OWNER TO postgres;

--
-- Name: crm_object_subcategory_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_object_subcategory_links_id_seq OWNED BY public.crm_object_subcategory_links.id;


--
-- Name: crm_objects_index; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_objects_index (
    object_key text NOT NULL,
    name text NOT NULL,
    address text,
    segment text NOT NULL,
    status text,
    source_codes text[] DEFAULT '{}'::text[] NOT NULL,
    pd_number text,
    expertise_number text,
    contract_number text,
    region_id integer,
    region_name text,
    registry_type text,
    tender_id integer,
    domrf_object_id text,
    doc_matches integer DEFAULT 0 NOT NULL,
    matched_files integer DEFAULT 0 NOT NULL,
    customer_name text,
    customer_inn text,
    contractor_name text,
    contractor_inn text,
    quality_tier text DEFAULT 'basic'::text NOT NULL,
    info_score integer DEFAULT 0 NOT NULL,
    info_flags jsonb DEFAULT '[]'::jsonb NOT NULL,
    search_text text DEFAULT ''::text NOT NULL,
    balance_holder text,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date
);


ALTER TABLE public.crm_objects_index OWNER TO postgres;

--
-- Name: crm_objects_index_meta; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_objects_index_meta (
    id integer DEFAULT 1 NOT NULL,
    row_count integer DEFAULT 0 NOT NULL,
    indexed_at timestamp with time zone,
    duration_ms integer,
    source_indexes_ok boolean DEFAULT false NOT NULL,
    last_error text,
    CONSTRAINT crm_objects_index_meta_id_check CHECK ((id = 1))
);


ALTER TABLE public.crm_objects_index_meta OWNER TO postgres;

--
-- Name: crm_opportunities; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_opportunities (
    id integer NOT NULL,
    lead_id integer,
    pipeline_id integer NOT NULL,
    stage_id integer NOT NULL,
    external_entity_id integer,
    account_id integer,
    title character varying(500) NOT NULL,
    amount numeric(15,2),
    margin numeric(10,2),
    probability numeric(5,2),
    expected_close_date date,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    owner_id integer,
    metadata jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_opportunities OWNER TO postgres;

--
-- Name: crm_opportunities_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_opportunities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_opportunities_id_seq OWNER TO postgres;

--
-- Name: crm_opportunities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_opportunities_id_seq OWNED BY public.crm_opportunities.id;


--
-- Name: crm_opportunity_stage_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_opportunity_stage_history (
    id integer NOT NULL,
    opportunity_id integer NOT NULL,
    from_stage_id integer,
    to_stage_id integer NOT NULL,
    changed_by integer,
    changed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_opportunity_stage_history OWNER TO postgres;

--
-- Name: crm_opportunity_stage_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_opportunity_stage_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_opportunity_stage_history_id_seq OWNER TO postgres;

--
-- Name: crm_opportunity_stage_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_opportunity_stage_history_id_seq OWNED BY public.crm_opportunity_stage_history.id;


--
-- Name: crm_pipeline_stages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_pipeline_stages (
    id integer NOT NULL,
    pipeline_id integer NOT NULL,
    stage_key character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    stage_order integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_pipeline_stages OWNER TO postgres;

--
-- Name: crm_pipeline_stages_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_pipeline_stages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_pipeline_stages_id_seq OWNER TO postgres;

--
-- Name: crm_pipeline_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_pipeline_stages_id_seq OWNED BY public.crm_pipeline_stages.id;


--
-- Name: crm_pipelines; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_pipelines (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    pipeline_role character varying(30) DEFAULT 'both'::character varying NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_pipelines OWNER TO postgres;

--
-- Name: crm_pipelines_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_pipelines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_pipelines_id_seq OWNER TO postgres;

--
-- Name: crm_pipelines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_pipelines_id_seq OWNED BY public.crm_pipelines.id;


--
-- Name: crm_product_categories; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_product_categories (
    id bigint NOT NULL,
    contour_code text NOT NULL,
    category_code text NOT NULL,
    category_name text NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_product_categories OWNER TO postgres;

--
-- Name: crm_product_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_product_categories_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_product_categories_id_seq OWNER TO postgres;

--
-- Name: crm_product_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_product_categories_id_seq OWNED BY public.crm_product_categories.id;


--
-- Name: crm_product_groups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_product_groups (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_product_groups OWNER TO postgres;

--
-- Name: crm_product_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_product_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_product_groups_id_seq OWNER TO postgres;

--
-- Name: crm_product_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_product_groups_id_seq OWNED BY public.crm_product_groups.id;


--
-- Name: crm_product_subcategories; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_product_subcategories (
    id bigint NOT NULL,
    category_id bigint NOT NULL,
    subcategory_code text NOT NULL,
    subcategory_name text NOT NULL,
    search_phrases jsonb DEFAULT '[]'::jsonb NOT NULL,
    negative_phrases jsonb DEFAULT '[]'::jsonb NOT NULL,
    technical_parameters jsonb DEFAULT '[]'::jsonb NOT NULL,
    brand_phrases jsonb DEFAULT '[]'::jsonb NOT NULL,
    source text DEFAULT 'seed'::text NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_product_subcategories OWNER TO postgres;

--
-- Name: crm_product_subcategories_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_product_subcategories_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_product_subcategories_id_seq OWNER TO postgres;

--
-- Name: crm_product_subcategories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_product_subcategories_id_seq OWNED BY public.crm_product_subcategories.id;


--
-- Name: crm_product_subcategory_terms; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_product_subcategory_terms (
    id bigint NOT NULL,
    subcategory_id bigint NOT NULL,
    term_type text NOT NULL,
    phrase text NOT NULL,
    weight integer DEFAULT 100 NOT NULL,
    source text DEFAULT 'seed'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_product_subcategory_terms OWNER TO postgres;

--
-- Name: crm_product_subcategory_terms_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_product_subcategory_terms_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_product_subcategory_terms_id_seq OWNER TO postgres;

--
-- Name: crm_product_subcategory_terms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_product_subcategory_terms_id_seq OWNED BY public.crm_product_subcategory_terms.id;


--
-- Name: crm_search_profile_groups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_search_profile_groups (
    id bigint NOT NULL,
    search_profile_id bigint NOT NULL,
    product_group_id bigint NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    priority_weight integer DEFAULT 100 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_search_profile_groups OWNER TO postgres;

--
-- Name: crm_search_profile_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_search_profile_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_search_profile_groups_id_seq OWNER TO postgres;

--
-- Name: crm_search_profile_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_search_profile_groups_id_seq OWNED BY public.crm_search_profile_groups.id;


--
-- Name: crm_search_profiles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_search_profiles (
    id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    owner_user_id bigint,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_search_profiles OWNER TO postgres;

--
-- Name: crm_search_profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_search_profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_search_profiles_id_seq OWNER TO postgres;

--
-- Name: crm_search_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_search_profiles_id_seq OWNED BY public.crm_search_profiles.id;


--
-- Name: crm_search_rules; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_search_rules (
    id bigint NOT NULL,
    scope text NOT NULL,
    search_profile_id bigint,
    product_group_id bigint,
    rule_type text NOT NULL,
    value text NOT NULL,
    weight integer DEFAULT 100 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    reason text,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT crm_search_rules_rule_type_check CHECK ((rule_type = ANY (ARRAY['include_keyword'::text, 'exclude_keyword'::text, 'include_phrase'::text, 'exclude_phrase'::text, 'okpd2_include'::text, 'okpd2_exclude'::text, 'region_include'::text, 'region_exclude'::text]))),
    CONSTRAINT crm_search_rules_scope_check CHECK ((scope = ANY (ARRAY['global'::text, 'profile'::text, 'product_group'::text, 'profile_group'::text])))
);


ALTER TABLE public.crm_search_rules OWNER TO postgres;

--
-- Name: crm_search_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_search_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_search_rules_id_seq OWNER TO postgres;

--
-- Name: crm_search_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_search_rules_id_seq OWNED BY public.crm_search_rules.id;


--
-- Name: crm_tasks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_tasks (
    id integer NOT NULL,
    entity_type character varying(30) NOT NULL,
    entity_id integer NOT NULL,
    title character varying(500) NOT NULL,
    due_date date,
    owner_id integer,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.crm_tasks OWNER TO postgres;

--
-- Name: crm_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_tasks_id_seq OWNER TO postgres;

--
-- Name: crm_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_tasks_id_seq OWNED BY public.crm_tasks.id;


--
-- Name: management_companies; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.management_companies (
    id integer NOT NULL,
    city text,
    name text NOT NULL,
    inn character varying(12),
    legal_address text,
    actual_address text,
    lat double precision,
    lon double precision,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.management_companies OWNER TO postgres;

--
-- Name: management_companies_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.management_companies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.management_companies_id_seq OWNER TO postgres;

--
-- Name: management_companies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.management_companies_id_seq OWNED BY public.management_companies.id;


--
-- Name: mc_departments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mc_departments (
    id integer NOT NULL,
    mc_id integer NOT NULL,
    department_type character varying(50) NOT NULL,
    address text,
    work_schedule text,
    reception_schedule text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT mc_departments_department_type_check CHECK (((department_type)::text = ANY ((ARRAY['general_director'::character varying, 'exploitation_management'::character varying, 'procurement_dept'::character varying, 'technical_production_dept'::character varying, 'planning_economic_dept'::character varying, 'technical_dept'::character varying, 'capital_repair_dept'::character varying, 'legal_dept'::character varying])::text[])))
);


ALTER TABLE public.mc_departments OWNER TO postgres;

--
-- Name: mc_departments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mc_departments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mc_departments_id_seq OWNER TO postgres;

--
-- Name: mc_departments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mc_departments_id_seq OWNED BY public.mc_departments.id;


--
-- Name: mc_employees; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mc_employees (
    id integer NOT NULL,
    department_id integer NOT NULL,
    full_name text NOT NULL,
    "position" text,
    mobile_phone text,
    office_phone text,
    birth_date date,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.mc_employees OWNER TO postgres;

--
-- Name: mc_employees_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mc_employees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mc_employees_id_seq OWNER TO postgres;

--
-- Name: mc_employees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mc_employees_id_seq OWNED BY public.mc_employees.id;


--
-- Name: mc_parking_links; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mc_parking_links (
    id integer NOT NULL,
    mc_id integer NOT NULL,
    parking_object_id integer NOT NULL,
    linked_at timestamp without time zone DEFAULT now(),
    notes text
);


ALTER TABLE public.mc_parking_links OWNER TO postgres;

--
-- Name: mc_parking_links_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mc_parking_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mc_parking_links_id_seq OWNER TO postgres;

--
-- Name: mc_parking_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mc_parking_links_id_seq OWNED BY public.mc_parking_links.id;


--
-- Name: nashdom_construction_objects; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.nashdom_construction_objects (
    id integer NOT NULL,
    object_id character varying(100) NOT NULL,
    name character varying(1000),
    region character varying(255),
    city character varying(255),
    address text,
    developer_inn character varying(20),
    developer_name character varying(500),
    organization_inn character varying(20),
    organization_name character varying(500),
    year_commissioned integer,
    construction_stage character varying(100),
    floors integer,
    residential_area numeric(12,2),
    underground_parking boolean DEFAULT false NOT NULL,
    parking_spaces_total integer,
    parking_spaces_underground integer,
    project_declaration_number character varying(100),
    first_publish_date date,
    last_update_date date,
    object_url text,
    raw_payload jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    wall_material character varying(255),
    passenger_elevators integer,
    freight_elevators integer,
    energy_efficiency character varying(50),
    raw_payload_radar jsonb
);


ALTER TABLE public.nashdom_construction_objects OWNER TO postgres;

--
-- Name: nashdom_construction_objects_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.nashdom_construction_objects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.nashdom_construction_objects_id_seq OWNER TO postgres;

--
-- Name: nashdom_construction_objects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.nashdom_construction_objects_id_seq OWNED BY public.nashdom_construction_objects.id;


--
-- Name: nashdom_developer_metrics; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.nashdom_developer_metrics (
    developer_inn character varying(20) NOT NULL,
    developer_name character varying(500),
    total_objects integer DEFAULT 0 NOT NULL,
    objects_with_parking integer DEFAULT 0 NOT NULL,
    avg_parking_size numeric(10,2),
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.nashdom_developer_metrics OWNER TO postgres;

--
-- Name: nc_lead_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.nc_lead_records (
    id integer NOT NULL,
    external_object_id text NOT NULL,
    stage text DEFAULT 'new'::text NOT NULL,
    manager_id integer,
    manager_comment text,
    qualification_type text,
    linked_opportunity_id integer,
    rejection_reason text,
    defer_until date,
    defer_reason text,
    taken_at timestamp with time zone,
    qualified_at timestamp with time zone,
    rejected_at timestamp with time zone,
    cached_title text,
    cached_address text,
    cached_score integer DEFAULT 0,
    cached_status_name text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    cached_developer_id text,
    cached_floors integer,
    cached_total_area numeric,
    cached_parking_spaces integer,
    cached_stage_pct numeric,
    cached_parking_candidate boolean DEFAULT false,
    cached_finishing_candidate boolean DEFAULT false,
    cached_waterproofing_candidate boolean DEFAULT false,
    cached_planned_commission_date date,
    cached_region text,
    cached_score_breakdown jsonb,
    cached_elevator_count integer,
    cached_contractor text,
    cached_designer text,
    CONSTRAINT nc_lead_records_qualification_type_check CHECK (((qualification_type = ANY (ARRAY['new_construction'::text, 'subcontract'::text, 'materials'::text, 'exploitation'::text])) OR (qualification_type IS NULL))),
    CONSTRAINT nc_lead_records_stage_check CHECK ((stage = ANY (ARRAY['new'::text, 'qualifying'::text, 'qualified'::text, 'deferred'::text, 'rejected'::text])))
);


ALTER TABLE public.nc_lead_records OWNER TO postgres;

--
-- Name: nc_lead_records_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.nc_lead_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.nc_lead_records_id_seq OWNER TO postgres;

--
-- Name: nc_lead_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.nc_lead_records_id_seq OWNED BY public.nc_lead_records.id;


--
-- Name: nc_lead_stage_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.nc_lead_stage_history (
    id integer NOT NULL,
    nc_lead_id integer NOT NULL,
    from_stage text,
    to_stage text NOT NULL,
    changed_by integer,
    comment text,
    changed_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.nc_lead_stage_history OWNER TO postgres;

--
-- Name: nc_lead_stage_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.nc_lead_stage_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.nc_lead_stage_history_id_seq OWNER TO postgres;

--
-- Name: nc_lead_stage_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.nc_lead_stage_history_id_seq OWNED BY public.nc_lead_stage_history.id;


--
-- Name: parking_prefunnel_objects; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.parking_prefunnel_objects (
    id integer NOT NULL,
    cadastral_number character varying(50) NOT NULL,
    address text,
    floors_underground integer,
    parking_spaces integer,
    stage_id integer,
    is_valid_object boolean,
    inspection_done boolean DEFAULT false,
    meeting_done boolean DEFAULT false,
    photos text,
    problem_type text,
    mc_contact text,
    mc_decision_maker text,
    contact_history text,
    meeting_date date,
    meeting_attendees text,
    needs_identified text,
    budget_signal text,
    next_step text,
    survey_request_sent boolean DEFAULT false,
    survey_scope text,
    survey_timeline text,
    linked_opportunity_id integer,
    last_activity_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.parking_prefunnel_objects OWNER TO postgres;

--
-- Name: parking_prefunnel_objects_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.parking_prefunnel_objects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.parking_prefunnel_objects_id_seq OWNER TO postgres;

--
-- Name: parking_prefunnel_objects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.parking_prefunnel_objects_id_seq OWNED BY public.parking_prefunnel_objects.id;


--
-- Name: parking_prefunnel_stage_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.parking_prefunnel_stage_history (
    id integer NOT NULL,
    object_id integer NOT NULL,
    from_stage_id integer,
    to_stage_id integer NOT NULL,
    changed_by integer,
    comment text,
    changed_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.parking_prefunnel_stage_history OWNER TO postgres;

--
-- Name: parking_prefunnel_stage_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.parking_prefunnel_stage_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.parking_prefunnel_stage_history_id_seq OWNER TO postgres;

--
-- Name: parking_prefunnel_stage_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.parking_prefunnel_stage_history_id_seq OWNED BY public.parking_prefunnel_stage_history.id;


--
-- Name: parking_prefunnel_stages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.parking_prefunnel_stages (
    id integer NOT NULL,
    stage_key character varying(50) NOT NULL,
    stage_name character varying(100) NOT NULL,
    stage_order integer NOT NULL,
    is_terminal boolean DEFAULT false,
    color_hex character varying(7)
);


ALTER TABLE public.parking_prefunnel_stages OWNER TO postgres;

--
-- Name: parking_prefunnel_stages_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.parking_prefunnel_stages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.parking_prefunnel_stages_id_seq OWNER TO postgres;

--
-- Name: parking_prefunnel_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.parking_prefunnel_stages_id_seq OWNED BY public.parking_prefunnel_stages.id;


--
-- Name: category_object_applicability id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category_object_applicability ALTER COLUMN id SET DEFAULT nextval('public.category_object_applicability_id_seq'::regclass);


--
-- Name: category_object_observations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category_object_observations ALTER COLUMN id SET DEFAULT nextval('public.category_object_observations_id_seq'::regclass);


--
-- Name: crm_activities id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_activities ALTER COLUMN id SET DEFAULT nextval('public.crm_activities_id_seq'::regclass);


--
-- Name: crm_ai_training_events id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_ai_training_events ALTER COLUMN id SET DEFAULT nextval('public.crm_ai_training_events_id_seq'::regclass);


--
-- Name: crm_computer_tz_items id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_computer_tz_items ALTER COLUMN id SET DEFAULT nextval('public.crm_computer_tz_items_id_seq'::regclass);


--
-- Name: crm_external_entities id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_external_entities ALTER COLUMN id SET DEFAULT nextval('public.crm_external_entities_id_seq'::regclass);


--
-- Name: crm_lead_conversions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_conversions ALTER COLUMN id SET DEFAULT nextval('public.crm_lead_conversions_id_seq'::regclass);


--
-- Name: crm_lead_disposition_reasons id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_disposition_reasons ALTER COLUMN id SET DEFAULT nextval('public.crm_lead_disposition_reasons_id_seq'::regclass);


--
-- Name: crm_lead_dispositions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_dispositions ALTER COLUMN id SET DEFAULT nextval('public.crm_lead_dispositions_id_seq'::regclass);


--
-- Name: crm_lead_inbox_stages id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_inbox_stages ALTER COLUMN id SET DEFAULT nextval('public.crm_lead_inbox_stages_id_seq'::regclass);


--
-- Name: crm_lead_routing_rules id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_routing_rules ALTER COLUMN id SET DEFAULT nextval('public.crm_lead_routing_rules_id_seq'::regclass);


--
-- Name: crm_leads id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_leads ALTER COLUMN id SET DEFAULT nextval('public.crm_leads_id_seq'::regclass);


--
-- Name: crm_object_ai_classifications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_ai_classifications ALTER COLUMN id SET DEFAULT nextval('public.crm_object_ai_classifications_id_seq'::regclass);


--
-- Name: crm_object_profile_decisions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_profile_decisions ALTER COLUMN id SET DEFAULT nextval('public.crm_object_profile_decisions_id_seq'::regclass);


--
-- Name: crm_object_subcategory_links id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_subcategory_links ALTER COLUMN id SET DEFAULT nextval('public.crm_object_subcategory_links_id_seq'::regclass);


--
-- Name: crm_opportunities id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunities ALTER COLUMN id SET DEFAULT nextval('public.crm_opportunities_id_seq'::regclass);


--
-- Name: crm_opportunity_stage_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunity_stage_history ALTER COLUMN id SET DEFAULT nextval('public.crm_opportunity_stage_history_id_seq'::regclass);


--
-- Name: crm_pipeline_stages id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipeline_stages ALTER COLUMN id SET DEFAULT nextval('public.crm_pipeline_stages_id_seq'::regclass);


--
-- Name: crm_pipelines id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipelines ALTER COLUMN id SET DEFAULT nextval('public.crm_pipelines_id_seq'::regclass);


--
-- Name: crm_product_categories id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_categories ALTER COLUMN id SET DEFAULT nextval('public.crm_product_categories_id_seq'::regclass);


--
-- Name: crm_product_groups id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_groups ALTER COLUMN id SET DEFAULT nextval('public.crm_product_groups_id_seq'::regclass);


--
-- Name: crm_product_subcategories id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategories ALTER COLUMN id SET DEFAULT nextval('public.crm_product_subcategories_id_seq'::regclass);


--
-- Name: crm_product_subcategory_terms id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategory_terms ALTER COLUMN id SET DEFAULT nextval('public.crm_product_subcategory_terms_id_seq'::regclass);


--
-- Name: crm_search_profile_groups id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profile_groups ALTER COLUMN id SET DEFAULT nextval('public.crm_search_profile_groups_id_seq'::regclass);


--
-- Name: crm_search_profiles id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profiles ALTER COLUMN id SET DEFAULT nextval('public.crm_search_profiles_id_seq'::regclass);


--
-- Name: crm_search_rules id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_rules ALTER COLUMN id SET DEFAULT nextval('public.crm_search_rules_id_seq'::regclass);


--
-- Name: crm_tasks id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_tasks ALTER COLUMN id SET DEFAULT nextval('public.crm_tasks_id_seq'::regclass);


--
-- Name: management_companies id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.management_companies ALTER COLUMN id SET DEFAULT nextval('public.management_companies_id_seq'::regclass);


--
-- Name: mc_departments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_departments ALTER COLUMN id SET DEFAULT nextval('public.mc_departments_id_seq'::regclass);


--
-- Name: mc_employees id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_employees ALTER COLUMN id SET DEFAULT nextval('public.mc_employees_id_seq'::regclass);


--
-- Name: mc_parking_links id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_parking_links ALTER COLUMN id SET DEFAULT nextval('public.mc_parking_links_id_seq'::regclass);


--
-- Name: nashdom_construction_objects id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nashdom_construction_objects ALTER COLUMN id SET DEFAULT nextval('public.nashdom_construction_objects_id_seq'::regclass);


--
-- Name: nc_lead_records id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nc_lead_records ALTER COLUMN id SET DEFAULT nextval('public.nc_lead_records_id_seq'::regclass);


--
-- Name: nc_lead_stage_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nc_lead_stage_history ALTER COLUMN id SET DEFAULT nextval('public.nc_lead_stage_history_id_seq'::regclass);


--
-- Name: parking_prefunnel_objects id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_objects ALTER COLUMN id SET DEFAULT nextval('public.parking_prefunnel_objects_id_seq'::regclass);


--
-- Name: parking_prefunnel_stage_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stage_history ALTER COLUMN id SET DEFAULT nextval('public.parking_prefunnel_stage_history_id_seq'::regclass);


--
-- Name: parking_prefunnel_stages id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stages ALTER COLUMN id SET DEFAULT nextval('public.parking_prefunnel_stages_id_seq'::regclass);


--
-- Name: category_object_applicability category_object_applicability_category_code_subcategory_cod_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category_object_applicability
    ADD CONSTRAINT category_object_applicability_category_code_subcategory_cod_key UNIQUE (category_code, subcategory_code, object_class, object_type, work_type);


--
-- Name: category_object_applicability category_object_applicability_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category_object_applicability
    ADD CONSTRAINT category_object_applicability_pkey PRIMARY KEY (id);


--
-- Name: category_object_observations category_object_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category_object_observations
    ADD CONSTRAINT category_object_observations_pkey PRIMARY KEY (id);


--
-- Name: category_object_priority_stats category_object_priority_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.category_object_priority_stats
    ADD CONSTRAINT category_object_priority_stats_pkey PRIMARY KEY (category_code, subcategory_code, object_class, object_type, work_type);


--
-- Name: crm_activities crm_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_activities
    ADD CONSTRAINT crm_activities_pkey PRIMARY KEY (id);


--
-- Name: crm_ai_training_events crm_ai_training_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_ai_training_events
    ADD CONSTRAINT crm_ai_training_events_pkey PRIMARY KEY (id);


--
-- Name: crm_computer_tz_cards crm_computer_tz_cards_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_computer_tz_cards
    ADD CONSTRAINT crm_computer_tz_cards_pkey PRIMARY KEY (object_key);


--
-- Name: crm_computer_tz_items crm_computer_tz_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_computer_tz_items
    ADD CONSTRAINT crm_computer_tz_items_pkey PRIMARY KEY (id);


--
-- Name: crm_external_entities crm_external_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_external_entities
    ADD CONSTRAINT crm_external_entities_pkey PRIMARY KEY (id);


--
-- Name: crm_external_entities crm_external_entities_source_type_source_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_external_entities
    ADD CONSTRAINT crm_external_entities_source_type_source_key_key UNIQUE (source_type, source_key);


--
-- Name: crm_lead_conversions crm_lead_conversions_lead_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_conversions
    ADD CONSTRAINT crm_lead_conversions_lead_id_key UNIQUE (lead_id);


--
-- Name: crm_lead_conversions crm_lead_conversions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_conversions
    ADD CONSTRAINT crm_lead_conversions_pkey PRIMARY KEY (id);


--
-- Name: crm_lead_disposition_reasons crm_lead_disposition_reasons_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_disposition_reasons
    ADD CONSTRAINT crm_lead_disposition_reasons_code_key UNIQUE (code);


--
-- Name: crm_lead_disposition_reasons crm_lead_disposition_reasons_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_disposition_reasons
    ADD CONSTRAINT crm_lead_disposition_reasons_pkey PRIMARY KEY (id);


--
-- Name: crm_lead_dispositions crm_lead_dispositions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_dispositions
    ADD CONSTRAINT crm_lead_dispositions_pkey PRIMARY KEY (id);


--
-- Name: crm_lead_inbox_stages crm_lead_inbox_stages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_inbox_stages
    ADD CONSTRAINT crm_lead_inbox_stages_pkey PRIMARY KEY (id);


--
-- Name: crm_lead_inbox_stages crm_lead_inbox_stages_stage_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_inbox_stages
    ADD CONSTRAINT crm_lead_inbox_stages_stage_key_key UNIQUE (stage_key);


--
-- Name: crm_lead_routing_rules crm_lead_routing_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_routing_rules
    ADD CONSTRAINT crm_lead_routing_rules_pkey PRIMARY KEY (id);


--
-- Name: crm_leads crm_leads_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_leads
    ADD CONSTRAINT crm_leads_pkey PRIMARY KEY (id);


--
-- Name: crm_object_ai_classifications crm_object_ai_classifications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_ai_classifications
    ADD CONSTRAINT crm_object_ai_classifications_pkey PRIMARY KEY (id);


--
-- Name: crm_object_profile_decisions crm_object_profile_decisions_object_key_search_profile_id_p_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_profile_decisions
    ADD CONSTRAINT crm_object_profile_decisions_object_key_search_profile_id_p_key UNIQUE (object_key, search_profile_id, product_group_id);


--
-- Name: crm_object_profile_decisions crm_object_profile_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_profile_decisions
    ADD CONSTRAINT crm_object_profile_decisions_pkey PRIMARY KEY (id);


--
-- Name: crm_object_subcategory_links crm_object_subcategory_links_object_key_contour_code_catego_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_subcategory_links
    ADD CONSTRAINT crm_object_subcategory_links_object_key_contour_code_catego_key UNIQUE (object_key, contour_code, category_code, subcategory_code);


--
-- Name: crm_object_subcategory_links crm_object_subcategory_links_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_subcategory_links
    ADD CONSTRAINT crm_object_subcategory_links_pkey PRIMARY KEY (id);


--
-- Name: crm_objects_index_meta crm_objects_index_meta_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_objects_index_meta
    ADD CONSTRAINT crm_objects_index_meta_pkey PRIMARY KEY (id);


--
-- Name: crm_objects_index crm_objects_index_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_objects_index
    ADD CONSTRAINT crm_objects_index_pkey PRIMARY KEY (object_key);


--
-- Name: crm_opportunities crm_opportunities_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunities
    ADD CONSTRAINT crm_opportunities_pkey PRIMARY KEY (id);


--
-- Name: crm_opportunity_stage_history crm_opportunity_stage_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunity_stage_history
    ADD CONSTRAINT crm_opportunity_stage_history_pkey PRIMARY KEY (id);


--
-- Name: crm_pipeline_stages crm_pipeline_stages_pipeline_id_stage_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipeline_stages
    ADD CONSTRAINT crm_pipeline_stages_pipeline_id_stage_key_key UNIQUE (pipeline_id, stage_key);


--
-- Name: crm_pipeline_stages crm_pipeline_stages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipeline_stages
    ADD CONSTRAINT crm_pipeline_stages_pkey PRIMARY KEY (id);


--
-- Name: crm_pipelines crm_pipelines_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipelines
    ADD CONSTRAINT crm_pipelines_code_key UNIQUE (code);


--
-- Name: crm_pipelines crm_pipelines_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipelines
    ADD CONSTRAINT crm_pipelines_pkey PRIMARY KEY (id);


--
-- Name: crm_product_categories crm_product_categories_contour_code_category_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_categories
    ADD CONSTRAINT crm_product_categories_contour_code_category_code_key UNIQUE (contour_code, category_code);


--
-- Name: crm_product_categories crm_product_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_categories
    ADD CONSTRAINT crm_product_categories_pkey PRIMARY KEY (id);


--
-- Name: crm_product_groups crm_product_groups_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_groups
    ADD CONSTRAINT crm_product_groups_code_key UNIQUE (code);


--
-- Name: crm_product_groups crm_product_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_groups
    ADD CONSTRAINT crm_product_groups_pkey PRIMARY KEY (id);


--
-- Name: crm_product_subcategories crm_product_subcategories_category_id_subcategory_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategories
    ADD CONSTRAINT crm_product_subcategories_category_id_subcategory_code_key UNIQUE (category_id, subcategory_code);


--
-- Name: crm_product_subcategories crm_product_subcategories_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategories
    ADD CONSTRAINT crm_product_subcategories_pkey PRIMARY KEY (id);


--
-- Name: crm_product_subcategory_terms crm_product_subcategory_terms_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategory_terms
    ADD CONSTRAINT crm_product_subcategory_terms_pkey PRIMARY KEY (id);


--
-- Name: crm_product_subcategory_terms crm_product_subcategory_terms_subcategory_id_term_type_phra_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategory_terms
    ADD CONSTRAINT crm_product_subcategory_terms_subcategory_id_term_type_phra_key UNIQUE (subcategory_id, term_type, phrase);


--
-- Name: crm_search_profile_groups crm_search_profile_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profile_groups
    ADD CONSTRAINT crm_search_profile_groups_pkey PRIMARY KEY (id);


--
-- Name: crm_search_profile_groups crm_search_profile_groups_search_profile_id_product_group_i_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profile_groups
    ADD CONSTRAINT crm_search_profile_groups_search_profile_id_product_group_i_key UNIQUE (search_profile_id, product_group_id);


--
-- Name: crm_search_profiles crm_search_profiles_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profiles
    ADD CONSTRAINT crm_search_profiles_code_key UNIQUE (code);


--
-- Name: crm_search_profiles crm_search_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profiles
    ADD CONSTRAINT crm_search_profiles_pkey PRIMARY KEY (id);


--
-- Name: crm_search_rules crm_search_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_rules
    ADD CONSTRAINT crm_search_rules_pkey PRIMARY KEY (id);


--
-- Name: crm_tasks crm_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_tasks
    ADD CONSTRAINT crm_tasks_pkey PRIMARY KEY (id);


--
-- Name: management_companies management_companies_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.management_companies
    ADD CONSTRAINT management_companies_pkey PRIMARY KEY (id);


--
-- Name: mc_departments mc_departments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_departments
    ADD CONSTRAINT mc_departments_pkey PRIMARY KEY (id);


--
-- Name: mc_employees mc_employees_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_employees
    ADD CONSTRAINT mc_employees_pkey PRIMARY KEY (id);


--
-- Name: mc_parking_links mc_parking_links_mc_id_parking_object_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_parking_links
    ADD CONSTRAINT mc_parking_links_mc_id_parking_object_id_key UNIQUE (mc_id, parking_object_id);


--
-- Name: mc_parking_links mc_parking_links_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_parking_links
    ADD CONSTRAINT mc_parking_links_pkey PRIMARY KEY (id);


--
-- Name: nashdom_construction_objects nashdom_construction_objects_object_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nashdom_construction_objects
    ADD CONSTRAINT nashdom_construction_objects_object_id_key UNIQUE (object_id);


--
-- Name: nashdom_construction_objects nashdom_construction_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nashdom_construction_objects
    ADD CONSTRAINT nashdom_construction_objects_pkey PRIMARY KEY (id);


--
-- Name: nashdom_developer_metrics nashdom_developer_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nashdom_developer_metrics
    ADD CONSTRAINT nashdom_developer_metrics_pkey PRIMARY KEY (developer_inn);


--
-- Name: nc_lead_records nc_lead_records_external_object_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nc_lead_records
    ADD CONSTRAINT nc_lead_records_external_object_id_key UNIQUE (external_object_id);


--
-- Name: nc_lead_records nc_lead_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nc_lead_records
    ADD CONSTRAINT nc_lead_records_pkey PRIMARY KEY (id);


--
-- Name: nc_lead_stage_history nc_lead_stage_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nc_lead_stage_history
    ADD CONSTRAINT nc_lead_stage_history_pkey PRIMARY KEY (id);


--
-- Name: parking_prefunnel_objects parking_prefunnel_objects_cadastral_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_objects
    ADD CONSTRAINT parking_prefunnel_objects_cadastral_number_key UNIQUE (cadastral_number);


--
-- Name: parking_prefunnel_objects parking_prefunnel_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_objects
    ADD CONSTRAINT parking_prefunnel_objects_pkey PRIMARY KEY (id);


--
-- Name: parking_prefunnel_stage_history parking_prefunnel_stage_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stage_history
    ADD CONSTRAINT parking_prefunnel_stage_history_pkey PRIMARY KEY (id);


--
-- Name: parking_prefunnel_stages parking_prefunnel_stages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stages
    ADD CONSTRAINT parking_prefunnel_stages_pkey PRIMARY KEY (id);


--
-- Name: parking_prefunnel_stages parking_prefunnel_stages_stage_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stages
    ADD CONSTRAINT parking_prefunnel_stages_stage_key_key UNIQUE (stage_key);


--
-- Name: idx_act_entity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_act_entity ON public.crm_activities USING btree (entity_type, entity_id);


--
-- Name: idx_crm_ai_training_events_object; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_ai_training_events_object ON public.crm_ai_training_events USING btree (object_key, created_at DESC);


--
-- Name: idx_crm_ai_training_events_profile_group; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_ai_training_events_profile_group ON public.crm_ai_training_events USING btree (search_profile_id, product_group_id, created_at DESC);


--
-- Name: idx_crm_object_profile_decisions_object; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_object_profile_decisions_object ON public.crm_object_profile_decisions USING btree (object_key);


--
-- Name: idx_crm_object_profile_decisions_queue; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_object_profile_decisions_queue ON public.crm_object_profile_decisions USING btree (search_profile_id, product_group_id, decision, priority_score DESC);


--
-- Name: idx_crm_objects_contract; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_contract ON public.crm_objects_index USING btree (contract_number) WHERE (contract_number IS NOT NULL);


--
-- Name: idx_crm_objects_expertise; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_expertise ON public.crm_objects_index USING btree (expertise_number) WHERE (expertise_number IS NOT NULL);


--
-- Name: idx_crm_objects_region; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_region ON public.crm_objects_index USING btree (region_id);


--
-- Name: idx_crm_objects_score; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_score ON public.crm_objects_index USING btree (info_score DESC);


--
-- Name: idx_crm_objects_search_trgm; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_search_trgm ON public.crm_objects_index USING gin (search_text public.gin_trgm_ops);


--
-- Name: idx_crm_objects_segment; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_segment ON public.crm_objects_index USING btree (segment);


--
-- Name: idx_crm_objects_tier; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_objects_tier ON public.crm_objects_index USING btree (quality_tier);


--
-- Name: idx_crm_search_rules_profile_group; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_search_rules_profile_group ON public.crm_search_rules USING btree (search_profile_id, product_group_id, is_active);


--
-- Name: idx_crm_search_rules_scope_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crm_search_rules_scope_active ON public.crm_search_rules USING btree (scope, is_active);


--
-- Name: idx_disp_lead; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_disp_lead ON public.crm_lead_dispositions USING btree (lead_id);


--
-- Name: idx_ext_ent_source; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ext_ent_source ON public.crm_external_entities USING btree (source_type, source_key);


--
-- Name: idx_leads_ext_ent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leads_ext_ent ON public.crm_leads USING btree (external_entity_id);


--
-- Name: idx_leads_pipeline; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leads_pipeline ON public.crm_leads USING btree (pipeline_id);


--
-- Name: idx_leads_score; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leads_score ON public.crm_leads USING btree (score DESC);


--
-- Name: idx_leads_stage; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leads_stage ON public.crm_leads USING btree (inbox_stage_id);


--
-- Name: idx_leads_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leads_status ON public.crm_leads USING btree (disposition_status);


--
-- Name: idx_mc_departments_mc_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mc_departments_mc_id ON public.mc_departments USING btree (mc_id);


--
-- Name: idx_mc_employees_dept_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mc_employees_dept_id ON public.mc_employees USING btree (department_id);


--
-- Name: idx_mc_links_mc_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mc_links_mc_id ON public.mc_parking_links USING btree (mc_id);


--
-- Name: idx_mc_links_parking_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mc_links_parking_id ON public.mc_parking_links USING btree (parking_object_id);


--
-- Name: idx_nc_history_lead; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nc_history_lead ON public.nc_lead_stage_history USING btree (nc_lead_id);


--
-- Name: idx_nc_leads_manager; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nc_leads_manager ON public.nc_lead_records USING btree (manager_id);


--
-- Name: idx_nc_leads_opp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nc_leads_opp ON public.nc_lead_records USING btree (linked_opportunity_id);


--
-- Name: idx_nc_leads_stage; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nc_leads_stage ON public.nc_lead_records USING btree (stage);


--
-- Name: idx_nco_dev_inn; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nco_dev_inn ON public.nashdom_construction_objects USING btree (developer_inn);


--
-- Name: idx_nco_parking; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nco_parking ON public.nashdom_construction_objects USING btree (underground_parking);


--
-- Name: idx_nco_region; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_nco_region ON public.nashdom_construction_objects USING btree (region);


--
-- Name: idx_opp_lead; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_opp_lead ON public.crm_opportunities USING btree (lead_id);


--
-- Name: idx_opp_pipeline; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_opp_pipeline ON public.crm_opportunities USING btree (pipeline_id);


--
-- Name: idx_opp_stage; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_opp_stage ON public.crm_opportunities USING btree (stage_id);


--
-- Name: idx_opp_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_opp_status ON public.crm_opportunities USING btree (status);


--
-- Name: idx_osh_opp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_osh_opp ON public.crm_opportunity_stage_history USING btree (opportunity_id);


--
-- Name: idx_ppf_history_object; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ppf_history_object ON public.parking_prefunnel_stage_history USING btree (object_id);


--
-- Name: idx_ppf_objects_cadnum; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ppf_objects_cadnum ON public.parking_prefunnel_objects USING btree (cadastral_number);


--
-- Name: idx_ppf_objects_stage; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ppf_objects_stage ON public.parking_prefunnel_objects USING btree (stage_id);


--
-- Name: idx_ps_pipeline; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ps_pipeline ON public.crm_pipeline_stages USING btree (pipeline_id);


--
-- Name: idx_tasks_entity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tasks_entity ON public.crm_tasks USING btree (entity_type, entity_id);


--
-- Name: ix_category_object_applicability_enabled; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_category_object_applicability_enabled ON public.category_object_applicability USING btree (enabled, category_code, subcategory_code);


--
-- Name: ix_category_object_observations_category; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_category_object_observations_category ON public.category_object_observations USING btree (category_code, subcategory_code, created_at DESC);


--
-- Name: ix_category_object_observations_tender; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_category_object_observations_tender ON public.category_object_observations USING btree (tender_id, registry_type, created_at DESC);


--
-- Name: ix_crm_computer_tz_items_category; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_computer_tz_items_category ON public.crm_computer_tz_items USING btree (category);


--
-- Name: ix_crm_computer_tz_items_object_key; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_computer_tz_items_object_key ON public.crm_computer_tz_items USING btree (object_key);


--
-- Name: ix_crm_object_ai_classifications_contract; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_object_ai_classifications_contract ON public.crm_object_ai_classifications USING btree (contract_number);


--
-- Name: ix_crm_object_ai_classifications_expertise; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_object_ai_classifications_expertise ON public.crm_object_ai_classifications USING btree (expertise_number);


--
-- Name: ix_crm_object_ai_classifications_priority; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_object_ai_classifications_priority ON public.crm_object_ai_classifications USING btree (priority_score DESC);


--
-- Name: ix_crm_object_ai_classifications_segment; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_object_ai_classifications_segment ON public.crm_object_ai_classifications USING btree (segment);


--
-- Name: ix_crm_object_subcategory_links_object; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_object_subcategory_links_object ON public.crm_object_subcategory_links USING btree (object_key, contour_code);


--
-- Name: ix_crm_product_subcategory_terms_subcategory; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_product_subcategory_terms_subcategory ON public.crm_product_subcategory_terms USING btree (subcategory_id, term_type, is_active);


--
-- Name: ux_crm_object_ai_classifications_object_key; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_crm_object_ai_classifications_object_key ON public.crm_object_ai_classifications USING btree (object_key);


--
-- Name: crm_ai_training_events crm_ai_training_events_product_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_ai_training_events
    ADD CONSTRAINT crm_ai_training_events_product_group_id_fkey FOREIGN KEY (product_group_id) REFERENCES public.crm_product_groups(id) ON DELETE SET NULL;


--
-- Name: crm_ai_training_events crm_ai_training_events_search_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_ai_training_events
    ADD CONSTRAINT crm_ai_training_events_search_profile_id_fkey FOREIGN KEY (search_profile_id) REFERENCES public.crm_search_profiles(id) ON DELETE SET NULL;


--
-- Name: crm_lead_conversions crm_lead_conversions_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_conversions
    ADD CONSTRAINT crm_lead_conversions_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.crm_leads(id);


--
-- Name: crm_lead_conversions crm_lead_conversions_target_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_conversions
    ADD CONSTRAINT crm_lead_conversions_target_pipeline_id_fkey FOREIGN KEY (target_pipeline_id) REFERENCES public.crm_pipelines(id);


--
-- Name: crm_lead_dispositions crm_lead_dispositions_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_dispositions
    ADD CONSTRAINT crm_lead_dispositions_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.crm_leads(id);


--
-- Name: crm_lead_dispositions crm_lead_dispositions_reason_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_dispositions
    ADD CONSTRAINT crm_lead_dispositions_reason_id_fkey FOREIGN KEY (reason_id) REFERENCES public.crm_lead_disposition_reasons(id);


--
-- Name: crm_lead_routing_rules crm_lead_routing_rules_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_lead_routing_rules
    ADD CONSTRAINT crm_lead_routing_rules_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.crm_pipelines(id);


--
-- Name: crm_leads crm_leads_external_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_leads
    ADD CONSTRAINT crm_leads_external_entity_id_fkey FOREIGN KEY (external_entity_id) REFERENCES public.crm_external_entities(id);


--
-- Name: crm_leads crm_leads_inbox_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_leads
    ADD CONSTRAINT crm_leads_inbox_stage_id_fkey FOREIGN KEY (inbox_stage_id) REFERENCES public.crm_lead_inbox_stages(id);


--
-- Name: crm_leads crm_leads_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_leads
    ADD CONSTRAINT crm_leads_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.crm_pipelines(id);


--
-- Name: crm_leads crm_leads_recommended_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_leads
    ADD CONSTRAINT crm_leads_recommended_pipeline_id_fkey FOREIGN KEY (recommended_pipeline_id) REFERENCES public.crm_pipelines(id);


--
-- Name: crm_object_profile_decisions crm_object_profile_decisions_product_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_profile_decisions
    ADD CONSTRAINT crm_object_profile_decisions_product_group_id_fkey FOREIGN KEY (product_group_id) REFERENCES public.crm_product_groups(id) ON DELETE CASCADE;


--
-- Name: crm_object_profile_decisions crm_object_profile_decisions_search_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_profile_decisions
    ADD CONSTRAINT crm_object_profile_decisions_search_profile_id_fkey FOREIGN KEY (search_profile_id) REFERENCES public.crm_search_profiles(id) ON DELETE CASCADE;


--
-- Name: crm_opportunities crm_opportunities_external_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunities
    ADD CONSTRAINT crm_opportunities_external_entity_id_fkey FOREIGN KEY (external_entity_id) REFERENCES public.crm_external_entities(id);


--
-- Name: crm_opportunities crm_opportunities_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunities
    ADD CONSTRAINT crm_opportunities_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.crm_leads(id);


--
-- Name: crm_opportunities crm_opportunities_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunities
    ADD CONSTRAINT crm_opportunities_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.crm_pipelines(id);


--
-- Name: crm_opportunities crm_opportunities_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunities
    ADD CONSTRAINT crm_opportunities_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.crm_pipeline_stages(id);


--
-- Name: crm_opportunity_stage_history crm_opportunity_stage_history_from_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunity_stage_history
    ADD CONSTRAINT crm_opportunity_stage_history_from_stage_id_fkey FOREIGN KEY (from_stage_id) REFERENCES public.crm_pipeline_stages(id);


--
-- Name: crm_opportunity_stage_history crm_opportunity_stage_history_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunity_stage_history
    ADD CONSTRAINT crm_opportunity_stage_history_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES public.crm_opportunities(id) ON DELETE CASCADE;


--
-- Name: crm_opportunity_stage_history crm_opportunity_stage_history_to_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_opportunity_stage_history
    ADD CONSTRAINT crm_opportunity_stage_history_to_stage_id_fkey FOREIGN KEY (to_stage_id) REFERENCES public.crm_pipeline_stages(id);


--
-- Name: crm_pipeline_stages crm_pipeline_stages_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_pipeline_stages
    ADD CONSTRAINT crm_pipeline_stages_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.crm_pipelines(id) ON DELETE CASCADE;


--
-- Name: crm_product_subcategories crm_product_subcategories_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategories
    ADD CONSTRAINT crm_product_subcategories_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.crm_product_categories(id) ON DELETE CASCADE;


--
-- Name: crm_product_subcategory_terms crm_product_subcategory_terms_subcategory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_product_subcategory_terms
    ADD CONSTRAINT crm_product_subcategory_terms_subcategory_id_fkey FOREIGN KEY (subcategory_id) REFERENCES public.crm_product_subcategories(id) ON DELETE CASCADE;


--
-- Name: crm_search_profile_groups crm_search_profile_groups_product_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profile_groups
    ADD CONSTRAINT crm_search_profile_groups_product_group_id_fkey FOREIGN KEY (product_group_id) REFERENCES public.crm_product_groups(id) ON DELETE CASCADE;


--
-- Name: crm_search_profile_groups crm_search_profile_groups_search_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_profile_groups
    ADD CONSTRAINT crm_search_profile_groups_search_profile_id_fkey FOREIGN KEY (search_profile_id) REFERENCES public.crm_search_profiles(id) ON DELETE CASCADE;


--
-- Name: crm_search_rules crm_search_rules_product_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_rules
    ADD CONSTRAINT crm_search_rules_product_group_id_fkey FOREIGN KEY (product_group_id) REFERENCES public.crm_product_groups(id) ON DELETE CASCADE;


--
-- Name: crm_search_rules crm_search_rules_search_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_search_rules
    ADD CONSTRAINT crm_search_rules_search_profile_id_fkey FOREIGN KEY (search_profile_id) REFERENCES public.crm_search_profiles(id) ON DELETE CASCADE;


--
-- Name: mc_departments mc_departments_mc_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_departments
    ADD CONSTRAINT mc_departments_mc_id_fkey FOREIGN KEY (mc_id) REFERENCES public.management_companies(id) ON DELETE CASCADE;


--
-- Name: mc_employees mc_employees_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_employees
    ADD CONSTRAINT mc_employees_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.mc_departments(id) ON DELETE CASCADE;


--
-- Name: mc_parking_links mc_parking_links_mc_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_parking_links
    ADD CONSTRAINT mc_parking_links_mc_id_fkey FOREIGN KEY (mc_id) REFERENCES public.management_companies(id) ON DELETE CASCADE;


--
-- Name: mc_parking_links mc_parking_links_parking_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mc_parking_links
    ADD CONSTRAINT mc_parking_links_parking_object_id_fkey FOREIGN KEY (parking_object_id) REFERENCES public.parking_prefunnel_objects(id) ON DELETE CASCADE;


--
-- Name: nc_lead_stage_history nc_lead_stage_history_nc_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.nc_lead_stage_history
    ADD CONSTRAINT nc_lead_stage_history_nc_lead_id_fkey FOREIGN KEY (nc_lead_id) REFERENCES public.nc_lead_records(id) ON DELETE CASCADE;


--
-- Name: parking_prefunnel_objects parking_prefunnel_objects_linked_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_objects
    ADD CONSTRAINT parking_prefunnel_objects_linked_opportunity_id_fkey FOREIGN KEY (linked_opportunity_id) REFERENCES public.crm_opportunities(id);


--
-- Name: parking_prefunnel_objects parking_prefunnel_objects_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_objects
    ADD CONSTRAINT parking_prefunnel_objects_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.parking_prefunnel_stages(id);


--
-- Name: parking_prefunnel_stage_history parking_prefunnel_stage_history_from_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stage_history
    ADD CONSTRAINT parking_prefunnel_stage_history_from_stage_id_fkey FOREIGN KEY (from_stage_id) REFERENCES public.parking_prefunnel_stages(id);


--
-- Name: parking_prefunnel_stage_history parking_prefunnel_stage_history_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stage_history
    ADD CONSTRAINT parking_prefunnel_stage_history_object_id_fkey FOREIGN KEY (object_id) REFERENCES public.parking_prefunnel_objects(id);


--
-- Name: parking_prefunnel_stage_history parking_prefunnel_stage_history_to_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parking_prefunnel_stage_history
    ADD CONSTRAINT parking_prefunnel_stage_history_to_stage_id_fkey FOREIGN KEY (to_stage_id) REFERENCES public.parking_prefunnel_stages(id);


--
-- PostgreSQL database dump complete
--

\unrestrict pFVipabe39KqBFMug7fEDnkEAimlwf9CPXpGElCVhRwv9iS1jnx4kvKReyS91xH

