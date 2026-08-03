--
-- PostgreSQL database dump
--

\restrict mZrRa0G49L5O3aOmP51nA5OwJ6zbObrGWKuU2nnC7fgQTs1UdW593A4sDqbuZXU

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


--
-- Name: update_all_tender_statuses(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_all_tender_statuses() RETURNS TABLE(table_name text, updated_new integer, updated_commission integer, updated_won integer, updated_bad integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_44fz_new INTEGER;
    v_44fz_commission INTEGER;
    v_44fz_won INTEGER;
    v_44fz_bad INTEGER;
    v_223fz_new INTEGER;
    v_223fz_commission INTEGER;
    v_223fz_won INTEGER;
    v_223fz_bad INTEGER;
BEGIN
    -- Обновляем статусы для 44ФЗ
    SELECT * INTO v_44fz_new, v_44fz_commission, v_44fz_won, v_44fz_bad
    FROM update_tender_statuses_44fz();
    
    -- Обновляем статусы для 223ФЗ
    SELECT * INTO v_223fz_new, v_223fz_commission, v_223fz_won, v_223fz_bad
    FROM update_tender_statuses_223fz();
    
    -- Возвращаем результаты для 44ФЗ
    RETURN QUERY SELECT 
        'reestr_contract_44_fz'::TEXT,
        v_44fz_new,
        v_44fz_commission,
        v_44fz_won,
        v_44fz_bad;
    
    -- Возвращаем результаты для 223ФЗ
    RETURN QUERY SELECT 
        'reestr_contract_223_fz'::TEXT,
        v_223fz_new,
        v_223fz_commission,
        v_223fz_won,
        v_223fz_bad;
END;
$$;


ALTER FUNCTION public.update_all_tender_statuses() OWNER TO postgres;

--
-- Name: FUNCTION update_all_tender_statuses(); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.update_all_tender_statuses() IS 'Обновляет статусы для всех закупок (44ФЗ и 223ФЗ). Возвращает статистику обновлений.';


--
-- Name: update_tender_statuses_223fz(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_tender_statuses_223fz() RETURNS TABLE(updated_new integer, updated_commission integer, updated_won integer, updated_bad integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_updated_new INTEGER := 0;
    v_updated_commission INTEGER := 0;
    v_updated_won INTEGER := 0;
    v_updated_bad INTEGER := 0;
BEGIN
    -- 1. Обновление статуса "Разыграна" - ПЕРВЫМ
    -- delivery_end_date IS NOT NULL AND delivery_end_date >= CURRENT_DATE + 90 дней
    WITH updated AS (
        UPDATE reestr_contract_223_fz
        SET status_id = 3
        WHERE delivery_end_date IS NOT NULL
          AND delivery_end_date >= CURRENT_DATE + INTERVAL '90 days'
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_won FROM updated;
    
    -- 2. Обновление статуса "Работа комиссии" - ВТОРЫМ
    -- end_date < CURRENT_DATE 
    -- И end_date >= CURRENT_DATE - 90 дней
    -- И delivery_end_date IS NULL
    WITH updated AS (
        UPDATE reestr_contract_223_fz
        SET status_id = 2
        WHERE end_date IS NOT NULL
          AND end_date < CURRENT_DATE
          AND end_date >= CURRENT_DATE - INTERVAL '90 days'
          AND delivery_end_date IS NULL
          AND (status_id IS NULL OR status_id != 3)  -- Не перезаписываем "Разыграна"
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_commission FROM updated;
    
    -- 3. Обновление статуса "Новая" - ТРЕТЬИМ
    -- end_date >= CURRENT_DATE
    WITH updated AS (
        UPDATE reestr_contract_223_fz
        SET status_id = 1
        WHERE end_date IS NOT NULL 
          AND end_date >= CURRENT_DATE
          AND (status_id IS NULL OR status_id != 3)  -- Не перезаписываем "Разыграна"
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_new FROM updated;
    
    -- 4. Обновление статуса "Плохие" - ПОСЛЕДНИМ (все остальные)
    WITH updated AS (
        UPDATE reestr_contract_223_fz
        SET status_id = 4
        WHERE NOT (
            -- "Разыграна"
            (delivery_end_date IS NOT NULL AND delivery_end_date >= CURRENT_DATE + INTERVAL '90 days')
            -- ИЛИ "Работа комиссии"
            OR (end_date IS NOT NULL 
                AND end_date < CURRENT_DATE 
                AND end_date >= CURRENT_DATE - INTERVAL '90 days'
                AND delivery_end_date IS NULL)
            -- ИЛИ "Новая"
            OR (end_date IS NOT NULL AND end_date >= CURRENT_DATE)
        )
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_bad FROM updated;
    
    RETURN QUERY SELECT v_updated_new, v_updated_commission, v_updated_won, v_updated_bad;
END;
$$;


ALTER FUNCTION public.update_tender_statuses_223fz() OWNER TO postgres;

--
-- Name: FUNCTION update_tender_statuses_223fz(); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.update_tender_statuses_223fz() IS 'Обновляет статусы закупок 223ФЗ согласно тем же правилам, что и 44ФЗ. Все статусы перезаписываются.';


--
-- Name: update_tender_statuses_44fz(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_tender_statuses_44fz() RETURNS TABLE(updated_new integer, updated_commission integer, updated_won integer, updated_bad integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_updated_new INTEGER := 0;
    v_updated_commission INTEGER := 0;
    v_updated_won INTEGER := 0;
    v_updated_bad INTEGER := 0;
BEGIN
    -- ВАЖНО: Порядок имеет значение! Сначала проверяем более специфичные условия
    
    -- 1. Обновление статуса "Разыграна" - ПЕРВЫМ (самое специфичное условие)
    -- delivery_end_date IS NOT NULL AND delivery_end_date >= CURRENT_DATE + 90 дней
    WITH updated AS (
        UPDATE reestr_contract_44_fz
        SET status_id = 3
        WHERE delivery_end_date IS NOT NULL
          AND delivery_end_date >= CURRENT_DATE + INTERVAL '90 days'
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_won FROM updated;
    
    -- 2. Обновление статуса "Работа комиссии" - ВТОРЫМ
    -- end_date < CURRENT_DATE 
    -- И end_date >= CURRENT_DATE - 90 дней
    -- И delivery_end_date IS NULL
    -- И НЕ имеет delivery_end_date >= CURRENT_DATE + 90 дней (уже обработано как "Разыграна")
    WITH updated AS (
        UPDATE reestr_contract_44_fz
        SET status_id = 2
        WHERE end_date IS NOT NULL
          AND end_date < CURRENT_DATE
          AND end_date >= CURRENT_DATE - INTERVAL '90 days'
          AND delivery_end_date IS NULL
          AND (status_id IS NULL OR status_id != 3)  -- Не перезаписываем "Разыграна"
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_commission FROM updated;
    
    -- 3. Обновление статуса "Новая" - ТРЕТЬИМ
    -- end_date >= CURRENT_DATE
    -- И НЕ имеет delivery_end_date >= CURRENT_DATE + 90 дней (уже обработано как "Разыграна")
    WITH updated AS (
        UPDATE reestr_contract_44_fz
        SET status_id = 1
        WHERE end_date IS NOT NULL 
          AND end_date >= CURRENT_DATE
          AND (status_id IS NULL OR status_id != 3)  -- Не перезаписываем "Разыграна"
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_new FROM updated;
    
    -- 4. Обновление статуса "Плохие" - ПОСЛЕДНИМ (все остальные)
    -- Все записи, которые не соответствуют ни одному из "хороших" статусов
    WITH updated AS (
        UPDATE reestr_contract_44_fz
        SET status_id = 4
        WHERE NOT (
            -- "Разыграна"
            (delivery_end_date IS NOT NULL AND delivery_end_date >= CURRENT_DATE + INTERVAL '90 days')
            -- ИЛИ "Работа комиссии"
            OR (end_date IS NOT NULL 
                AND end_date < CURRENT_DATE 
                AND end_date >= CURRENT_DATE - INTERVAL '90 days'
                AND delivery_end_date IS NULL)
            -- ИЛИ "Новая"
            OR (end_date IS NOT NULL AND end_date >= CURRENT_DATE)
        )
        RETURNING id
    )
    SELECT COUNT(*) INTO v_updated_bad FROM updated;
    
    RETURN QUERY SELECT v_updated_new, v_updated_commission, v_updated_won, v_updated_bad;
END;
$$;


ALTER FUNCTION public.update_tender_statuses_44fz() OWNER TO postgres;

--
-- Name: FUNCTION update_tender_statuses_44fz(); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.update_tender_statuses_44fz() IS 'Обновляет статусы закупок 44ФЗ согласно правилам: Новые (end_date >= CURRENT_DATE), Работа комиссии (end_date < CURRENT_DATE AND end_date >= CURRENT_DATE - 90 дней AND delivery_end_date IS NULL), Разыграна (delivery_end_date IS NOT NULL AND delivery_end_date >= CURRENT_DATE + 90 дней), Плохие (все остальные). Все статусы перезаписываются.';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: achievements; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.achievements (
    id bigint NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    icon_url character varying(200) NOT NULL,
    icon_emoji character varying(10) NOT NULL,
    condition_type character varying(30) NOT NULL,
    condition_data jsonb NOT NULL,
    reward_xp integer NOT NULL,
    reward_points integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.achievements OWNER TO postgres;

--
-- Name: achievements_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.achievements ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.achievements_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ai_analysis_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ai_analysis_logs (
    id bigint NOT NULL,
    analysis_type character varying(50) NOT NULL,
    analysis_data jsonb NOT NULL,
    confidence double precision,
    win_probability double precision,
    sources_count integer NOT NULL,
    missing_data_count integer NOT NULL,
    validation_status character varying(20) NOT NULL,
    validation_notes text NOT NULL,
    actual_result character varying(50) NOT NULL,
    accuracy_score double precision,
    admin_notes text NOT NULL,
    is_flagged boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    validated_at timestamp with time zone,
    analyzed_at timestamp with time zone,
    tender_id bigint,
    user_id bigint
);


ALTER TABLE public.ai_analysis_logs OWNER TO postgres;

--
-- Name: ai_analysis_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.ai_analysis_logs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.ai_analysis_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ai_quality_metrics; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ai_quality_metrics (
    id bigint NOT NULL,
    date date NOT NULL,
    total_analyses integer NOT NULL,
    avg_confidence double precision NOT NULL,
    avg_win_probability double precision NOT NULL,
    analyses_with_result integer NOT NULL,
    avg_accuracy double precision,
    type_distribution jsonb NOT NULL,
    issues_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.ai_quality_metrics OWNER TO postgres;

--
-- Name: ai_quality_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.ai_quality_metrics ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.ai_quality_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ai_validation_reports; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ai_validation_reports (
    id bigint NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL,
    total_analyses integer NOT NULL,
    valid_analyses integer NOT NULL,
    invalid_analyses integer NOT NULL,
    warning_analyses integer NOT NULL,
    avg_accuracy double precision,
    avg_confidence double precision,
    avg_win_probability double precision,
    issues jsonb NOT NULL,
    recommendations jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    created_by_id bigint
);


ALTER TABLE public.ai_validation_reports OWNER TO postgres;

--
-- Name: ai_validation_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.ai_validation_reports ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.ai_validation_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: analytics_snapshots; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.analytics_snapshots (
    id bigint NOT NULL,
    snapshot_type character varying(20) NOT NULL,
    data jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    user_id bigint
);


ALTER TABLE public.analytics_snapshots OWNER TO postgres;

--
-- Name: analytics_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.analytics_snapshots ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.analytics_snapshots_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: application_forms; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.application_forms (
    id bigint NOT NULL,
    form_data jsonb NOT NULL,
    status character varying(20) NOT NULL,
    validation_errors jsonb NOT NULL,
    validation_warnings jsonb NOT NULL,
    submitted_at timestamp with time zone,
    submission_id character varying(255) NOT NULL,
    attached_documents jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    participation_id bigint,
    tender_id bigint NOT NULL,
    user_id bigint NOT NULL,
    template_id bigint
);


ALTER TABLE public.application_forms OWNER TO postgres;

--
-- Name: application_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.application_forms ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.application_forms_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: application_templates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.application_templates (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    template_data jsonb NOT NULL,
    category character varying(100) NOT NULL,
    platform character varying(100) NOT NULL,
    is_default boolean NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.application_templates OWNER TO postgres;

--
-- Name: application_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.application_templates ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.application_templates_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_enrichment_backfill_backup; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_enrichment_backfill_backup (
    queue_id integer,
    contract_reg_number character varying(255),
    table_source character varying(255),
    queue_status character varying(50),
    completed_at timestamp without time zone,
    queue_error text,
    processed_id bigint,
    file_name text,
    file_status text,
    backed_up_at timestamp with time zone
);


ALTER TABLE public.audit_enrichment_backfill_backup OWNER TO postgres;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    action character varying(50) NOT NULL,
    resource_id integer,
    ip_address inet,
    user_agent text NOT NULL,
    changes jsonb NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    resource_type_id integer,
    user_id bigint,
    CONSTRAINT audit_logs_resource_id_check CHECK ((resource_id >= 0))
);


ALTER TABLE public.audit_logs OWNER TO postgres;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.audit_logs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_no_links_requeue_backup; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_no_links_requeue_backup (
    id integer,
    contract_reg_number character varying(255),
    table_source character varying(255),
    status character varying(50),
    worker_id integer,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    error_message text,
    created_at timestamp without time zone,
    user_id integer,
    priority integer,
    backed_up_at timestamp with time zone
);


ALTER TABLE public.audit_no_links_requeue_backup OWNER TO postgres;

--
-- Name: audit_partial_pdf_backup_group1; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_partial_pdf_backup_group1 (
    queue_id integer,
    contract_reg_number character varying(255),
    table_source character varying(255),
    queue_status character varying(50),
    queue_worker_id integer,
    queue_started_at timestamp without time zone,
    queue_completed_at timestamp without time zone,
    queue_error_message text,
    processed_id bigint,
    tender_id bigint,
    file_name text,
    file_status text,
    is_interesting boolean,
    progress_cursor integer,
    resume_attempts integer,
    last_resume_cursor integer,
    file_error_message text,
    backed_up_at timestamp with time zone
);


ALTER TABLE public.audit_partial_pdf_backup_group1 OWNER TO postgres;

--
-- Name: audit_partial_pdf_backup_group1_r2; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_partial_pdf_backup_group1_r2 (
    queue_id integer,
    queue_status character varying(50),
    worker_id integer,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    queue_error_message text,
    processed_id bigint,
    file_name text,
    file_status text,
    progress_cursor integer,
    resume_attempts integer,
    file_error_message text,
    backed_up_at timestamp with time zone
);


ALTER TABLE public.audit_partial_pdf_backup_group1_r2 OWNER TO postgres;

--
-- Name: audit_today_error_requeue_backup; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_today_error_requeue_backup (
    id integer,
    contract_reg_number character varying(255),
    table_source character varying(255),
    status character varying(50),
    worker_id integer,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    error_message text,
    created_at timestamp without time zone,
    user_id integer,
    priority integer,
    backed_up_at timestamp with time zone
);


ALTER TABLE public.audit_today_error_requeue_backup OWNER TO postgres;

--
-- Name: audit_unclear_mis_migrate_223_backup_20260722_101045; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_unclear_mis_migrate_223_backup_20260722_101045 (
    fz text,
    id integer,
    contract_number text,
    tender_link text,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text,
    initial_price numeric,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    delivery_region text,
    delivery_address text,
    region_id integer,
    placer text,
    placer_inn text,
    status_id integer
);


ALTER TABLE public.audit_unclear_mis_migrate_223_backup_20260722_101045 OWNER TO postgres;

--
-- Name: audit_unclear_mis_migrate_backup_20260722_101045; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_unclear_mis_migrate_backup_20260722_101045 (
    fz text,
    id integer,
    contract_number text,
    tender_link text,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text,
    initial_price numeric,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer
);


ALTER TABLE public.audit_unclear_mis_migrate_backup_20260722_101045 OWNER TO postgres;

--
-- Name: backup_doc_stop_superuser_20260729; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.backup_doc_stop_superuser_20260729 (
    id integer,
    user_id integer,
    phrase text,
    setting_id integer,
    created_at timestamp with time zone
);


ALTER TABLE public.backup_doc_stop_superuser_20260729 OWNER TO postgres;

--
-- Name: backup_stop_words_superuser_20260729; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.backup_stop_words_superuser_20260729 (
    id integer,
    user_id integer,
    stop_word text,
    setting_id integer
);


ALTER TABLE public.backup_stop_words_superuser_20260729 OWNER TO postgres;

--
-- Name: backup_uss_superuser_20260729; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.backup_uss_superuser_20260729 (
    user_id integer,
    region_id integer,
    category_id integer,
    updated_at timestamp without time zone
);


ALTER TABLE public.backup_uss_superuser_20260729 OWNER TO postgres;

--
-- Name: calendar_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.calendar_settings (
    id bigint NOT NULL,
    default_travel_mode character varying(20) NOT NULL,
    default_buffer_minutes integer NOT NULL,
    protected_times_json jsonb NOT NULL,
    reminder_rules_json jsonb NOT NULL,
    auto_optimize_routes boolean NOT NULL,
    show_travel_warnings boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.calendar_settings OWNER TO postgres;

--
-- Name: calendar_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.calendar_settings ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.calendar_settings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: calibration_metrics; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.calibration_metrics (
    id bigint NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL,
    total_samples integer NOT NULL,
    train_samples integer NOT NULL,
    test_samples integer NOT NULL,
    avg_accuracy double precision,
    train_accuracy double precision,
    test_accuracy double precision,
    brier_score double precision,
    brier_score_train double precision,
    brier_score_test double precision,
    calibration_curve_data jsonb NOT NULL,
    calibration_curve_slope double precision,
    overconfidence_rate double precision,
    underconfidence_rate double precision,
    accuracy_by_category jsonb NOT NULL,
    accuracy_by_region jsonb NOT NULL,
    errors_by_factor jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    calibration_weights_id bigint
);


ALTER TABLE public.calibration_metrics OWNER TO postgres;

--
-- Name: calibration_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.calibration_metrics ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.calibration_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: calibration_weights; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.calibration_weights (
    id bigint NOT NULL,
    version integer NOT NULL,
    ai_weight_default double precision NOT NULL,
    ai_weight_high double precision NOT NULL,
    ai_weight_medium double precision NOT NULL,
    ai_weight_low double precision NOT NULL,
    confidence_threshold_high double precision NOT NULL,
    confidence_threshold_medium double precision NOT NULL,
    heuristic_user_match_weight double precision NOT NULL,
    heuristic_requirement_fit_weight double precision NOT NULL,
    heuristic_competition_weight double precision NOT NULL,
    heuristic_market_trend_weight double precision NOT NULL,
    heuristic_historical_weight double precision NOT NULL,
    accuracy_before double precision,
    accuracy_after double precision,
    brier_score double precision,
    calibration_curve_slope double precision,
    is_active boolean NOT NULL,
    is_validated boolean NOT NULL,
    samples_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    applied_at timestamp with time zone,
    notes text NOT NULL
);


ALTER TABLE public.calibration_weights OWNER TO postgres;

--
-- Name: calibration_weights_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.calibration_weights ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.calibration_weights_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: challenges; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.challenges (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    icon_emoji character varying(10) NOT NULL,
    challenge_type character varying(20) NOT NULL,
    action_type character varying(30) NOT NULL,
    target_value integer NOT NULL,
    condition_data jsonb NOT NULL,
    start_date timestamp with time zone NOT NULL,
    end_date timestamp with time zone NOT NULL,
    is_active boolean NOT NULL,
    reward_type character varying(20) NOT NULL,
    reward_value integer NOT NULL,
    reward_data jsonb NOT NULL,
    priority integer NOT NULL,
    is_featured boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.challenges OWNER TO postgres;

--
-- Name: challenges_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.challenges ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.challenges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: checklist_items; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.checklist_items (
    id bigint NOT NULL,
    stage character varying(20) NOT NULL,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    is_completed boolean NOT NULL,
    completed_at timestamp with time zone,
    "order" integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    completed_by_id bigint,
    participation_id bigint NOT NULL,
    related_document_id bigint
);


ALTER TABLE public.checklist_items OWNER TO postgres;

--
-- Name: checklist_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.checklist_items ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.checklist_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: collection_codes_okpd; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.collection_codes_okpd (
    id integer NOT NULL,
    main_code character varying(20),
    sub_code character varying(20),
    parent_id integer,
    name character varying(900)
);


ALTER TABLE public.collection_codes_okpd OWNER TO postgres;

--
-- Name: collection_codes_okpd_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.collection_codes_okpd_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.collection_codes_okpd_id_seq OWNER TO postgres;

--
-- Name: collection_codes_okpd_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.collection_codes_okpd_id_seq OWNED BY public.collection_codes_okpd.id;


--
-- Name: competitors; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.competitors (
    id bigint NOT NULL,
    identifier character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    inn character varying(20) NOT NULL,
    region character varying(100) NOT NULL,
    industry character varying(100) NOT NULL,
    total_participations integer NOT NULL,
    total_wins integer NOT NULL,
    win_rate double precision NOT NULL,
    total_won_amount numeric(15,2) NOT NULL,
    average_win_price numeric(15,2) NOT NULL,
    pricing_strategy jsonb NOT NULL,
    participation_pattern jsonb NOT NULL,
    customer_connections jsonb NOT NULL,
    suspicious_patterns jsonb NOT NULL,
    collusion_score double precision NOT NULL,
    geography jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_analyzed_at timestamp with time zone
);


ALTER TABLE public.competitors OWNER TO postgres;

--
-- Name: competitors_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.competitors ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.competitors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: consultations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.consultations (
    id bigint NOT NULL,
    consultation_type character varying(50) NOT NULL,
    scheduled_at timestamp with time zone NOT NULL,
    duration_minutes integer NOT NULL,
    status character varying(20) NOT NULL,
    topic character varying(255) NOT NULL,
    description text NOT NULL,
    notes text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    user_id bigint NOT NULL
);


ALTER TABLE public.consultations OWNER TO postgres;

--
-- Name: consultations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.consultations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.consultations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: contact; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.contact (
    id bigint NOT NULL,
    full_name text NOT NULL,
    department text,
    "position" text,
    birth_date date,
    phone_mobile text,
    email text,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.contact OWNER TO postgres;

--
-- Name: contact_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.contact_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.contact_id_seq OWNER TO postgres;

--
-- Name: contact_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.contact_id_seq OWNED BY public.contact.id;


--
-- Name: contact_link; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.contact_link (
    id bigint NOT NULL,
    contact_id bigint NOT NULL,
    customer_id bigint,
    contractor_id bigint,
    deal_id bigint,
    role text,
    is_primary boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT contact_link_target_not_null CHECK (((customer_id IS NOT NULL) OR (contractor_id IS NOT NULL) OR (deal_id IS NOT NULL)))
);


ALTER TABLE public.contact_link OWNER TO postgres;

--
-- Name: contact_link_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.contact_link_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.contact_link_id_seq OWNER TO postgres;

--
-- Name: contact_link_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.contact_link_id_seq OWNED BY public.contact_link.id;


--
-- Name: contract_category_scores; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.contract_category_scores (
    contract_number character varying(100) NOT NULL,
    category_code character varying(100) NOT NULL,
    score smallint DEFAULT 5 NOT NULL,
    classified_by character varying(50) DEFAULT 'qwen2.5:7b'::character varying,
    classified_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.contract_category_scores OWNER TO postgres;

--
-- Name: contractor; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.contractor (
    id integer NOT NULL,
    short_name text NOT NULL,
    full_name text NOT NULL,
    inn character varying(12) NOT NULL,
    kpp character varying(9),
    legal_address text NOT NULL,
    phone text,
    email text
);


ALTER TABLE public.contractor OWNER TO postgres;

--
-- Name: contractor_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.contractor_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.contractor_id_seq OWNER TO postgres;

--
-- Name: contractor_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.contractor_id_seq OWNED BY public.contractor.id;


--
-- Name: contractor_role; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.contractor_role (
    id bigint NOT NULL,
    contractor_id bigint NOT NULL,
    role text NOT NULL,
    is_primary boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT contractor_role_role_check CHECK ((role = ANY (ARRAY['contractor'::text, 'designer'::text, 'supplier'::text])))
);


ALTER TABLE public.contractor_role OWNER TO postgres;

--
-- Name: contractor_role_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.contractor_role_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.contractor_role_id_seq OWNER TO postgres;

--
-- Name: contractor_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.contractor_role_id_seq OWNED BY public.contractor_role.id;


--
-- Name: crm_docs_priority_hints; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_docs_priority_hints (
    id bigint NOT NULL,
    tender_id bigint NOT NULL,
    registry_type text NOT NULL,
    contract_number text,
    contour text NOT NULL,
    ai_priority_score integer DEFAULT 0 NOT NULL,
    ai_profile text,
    ai_reason text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_docs_priority_hints OWNER TO postgres;

--
-- Name: crm_docs_priority_hints_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_docs_priority_hints_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_docs_priority_hints_id_seq OWNER TO postgres;

--
-- Name: crm_docs_priority_hints_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_docs_priority_hints_id_seq OWNED BY public.crm_docs_priority_hints.id;


--
-- Name: crm_object_type_classifications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_object_type_classifications (
    id bigint NOT NULL,
    object_uid text,
    tender_id bigint,
    contract_number text,
    registry_type text,
    source_table text,
    classification_scope text DEFAULT 'object'::text NOT NULL,
    primary_class_code text,
    primary_class_name text,
    secondary_class_code text,
    secondary_class_name text,
    object_type_code text,
    object_type_name text,
    work_type_code text,
    work_type_name text,
    confidence numeric(5,4),
    classifier_source text DEFAULT 'rule'::text NOT NULL,
    model_name text,
    model_version text,
    prompt_version text,
    input_snapshot_json jsonb,
    output_json jsonb,
    review_status text DEFAULT 'auto_generated'::text NOT NULL,
    manager_comment text,
    is_active boolean DEFAULT true NOT NULL,
    last_detected_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_object_type_classifications OWNER TO postgres;

--
-- Name: TABLE crm_object_type_classifications; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.crm_object_type_classifications IS 'Классификация типа объекта для tender_monitor: социальный/коммерческий/инфраструктура -> школа/больница/дорога/мост и т.д. Используется для маршрутизации поиска, карточек и будущего датасета дообучения.';


--
-- Name: crm_object_type_classifications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_object_type_classifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_object_type_classifications_id_seq OWNER TO postgres;

--
-- Name: crm_object_type_classifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_object_type_classifications_id_seq OWNED BY public.crm_object_type_classifications.id;


--
-- Name: crm_unified_object_links; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_unified_object_links (
    id bigint NOT NULL,
    object_uid text NOT NULL,
    tender_id bigint,
    registry_type text,
    contract_number text,
    link_type text DEFAULT 'matched'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_unified_object_links OWNER TO postgres;

--
-- Name: crm_unified_object_links_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_unified_object_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_unified_object_links_id_seq OWNER TO postgres;

--
-- Name: crm_unified_object_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_unified_object_links_id_seq OWNED BY public.crm_unified_object_links.id;


--
-- Name: crm_unified_objects; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_unified_objects (
    id bigint NOT NULL,
    object_uid text NOT NULL,
    object_name text NOT NULL,
    region_name text,
    address text,
    domrf_object_id text,
    expertise_number text,
    expertise_date date,
    planner_name text,
    customer_name text,
    predicted_tender_date date,
    ai_priority_score integer DEFAULT 0 NOT NULL,
    ai_priority_reason text,
    ai_segment text,
    status text DEFAULT 'idea'::text NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_unified_objects OWNER TO postgres;

--
-- Name: crm_unified_objects_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_unified_objects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_unified_objects_id_seq OWNER TO postgres;

--
-- Name: crm_unified_objects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_unified_objects_id_seq OWNED BY public.crm_unified_objects.id;


--
-- Name: crm_unified_signals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.crm_unified_signals (
    id bigint NOT NULL,
    object_uid text NOT NULL,
    signal_source text NOT NULL,
    signal_type text,
    payload_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    signal_date timestamp with time zone,
    confidence integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.crm_unified_signals OWNER TO postgres;

--
-- Name: crm_unified_signals_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.crm_unified_signals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crm_unified_signals_id_seq OWNER TO postgres;

--
-- Name: crm_unified_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.crm_unified_signals_id_seq OWNED BY public.crm_unified_signals.id;


--
-- Name: customer; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.customer (
    id integer NOT NULL,
    customer_short_name text,
    customer_full_name text,
    customer_inn character varying(12) NOT NULL,
    customer_kpp character varying(9),
    customer_legal_address text,
    customer_actual_address text,
    contact_phone text,
    contact_email text,
    contact text
);


ALTER TABLE public.customer OWNER TO postgres;

--
-- Name: customer_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.customer_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.customer_id_seq OWNER TO postgres;

--
-- Name: customer_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.customer_id_seq OWNED BY public.customer.id;


--
-- Name: customer_role; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.customer_role (
    id bigint NOT NULL,
    customer_id bigint NOT NULL,
    role text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT customer_role_role_check CHECK ((role = 'customer'::text))
);


ALTER TABLE public.customer_role OWNER TO postgres;

--
-- Name: customer_role_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.customer_role_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.customer_role_id_seq OWNER TO postgres;

--
-- Name: customer_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.customer_role_id_seq OWNED BY public.customer_role.id;


--
-- Name: customers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.customers (
    id bigint NOT NULL,
    inn character varying(20) NOT NULL,
    name character varying(255) NOT NULL,
    legal_name character varying(500) NOT NULL,
    contact_email character varying(254) NOT NULL,
    contact_phone character varying(20) NOT NULL,
    website character varying(200) NOT NULL,
    address text NOT NULL,
    region character varying(100) NOT NULL,
    city character varying(100) NOT NULL,
    financial_data jsonb NOT NULL,
    reliability_rating character varying(20) NOT NULL,
    contracts_total integer NOT NULL,
    contracts_terminated integer NOT NULL,
    termination_rate double precision NOT NULL,
    average_payment_days double precision NOT NULL,
    court_cases_count integer NOT NULL,
    fas_complaints_count integer NOT NULL,
    recommendations jsonb NOT NULL,
    interaction_history jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_analyzed_at timestamp with time zone
);


ALTER TABLE public.customers OWNER TO postgres;

--
-- Name: customers_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.customers ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.customers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: daily_quests; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.daily_quests (
    id bigint NOT NULL,
    quest_type character varying(30) NOT NULL,
    target_count integer NOT NULL,
    current_count integer NOT NULL,
    reward_xp integer NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.daily_quests OWNER TO postgres;

--
-- Name: daily_quests_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.daily_quests ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.daily_quests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.dates (
    id integer NOT NULL,
    entry_date date DEFAULT CURRENT_DATE NOT NULL
);


ALTER TABLE public.dates OWNER TO postgres;

--
-- Name: dates_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.dates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.dates_id_seq OWNER TO postgres;

--
-- Name: dates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.dates_id_seq OWNED BY public.dates.id;


--
-- Name: deadline_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deadline_events (
    id bigint NOT NULL,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    deadline_at timestamp with time zone NOT NULL,
    reminder_at timestamp with time zone,
    event_type character varying(50) NOT NULL,
    priority character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    reminder_sent_3d boolean NOT NULL,
    reminder_sent_1d boolean NOT NULL,
    reminder_sent_3h boolean NOT NULL,
    synced_with_outlook boolean NOT NULL,
    synced_with_google boolean NOT NULL,
    external_event_id character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    participation_id bigint,
    tender_id bigint,
    user_id bigint NOT NULL,
    escalation_sent boolean NOT NULL,
    escalation_sent_at timestamp with time zone,
    amocrm_task_id character varying(255) NOT NULL,
    bitrix24_task_id character varying(255) NOT NULL,
    synced_with_crm boolean NOT NULL,
    buffer_minutes integer NOT NULL,
    duration_minutes integer NOT NULL,
    location_address character varying(500) NOT NULL,
    location_lat numeric(9,6),
    location_lon numeric(9,6),
    reminder_travel_sent_at timestamp with time zone,
    travel_mode character varying(20) NOT NULL,
    travel_time_minutes integer
);


ALTER TABLE public.deadline_events OWNER TO postgres;

--
-- Name: deadline_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.deadline_events ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deadline_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: deal_chat; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deal_chat (
    id bigint NOT NULL,
    deal_id bigint NOT NULL,
    sender_id bigint,
    sender_type text NOT NULL,
    message_text text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_read boolean DEFAULT false,
    metadata jsonb,
    CONSTRAINT deal_chat_sender_type_check CHECK ((sender_type = ANY (ARRAY['user'::text, 'ai_agent'::text])))
);


ALTER TABLE public.deal_chat OWNER TO postgres;

--
-- Name: deal_chat_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.deal_chat_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deal_chat_id_seq OWNER TO postgres;

--
-- Name: deal_chat_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.deal_chat_id_seq OWNED BY public.deal_chat.id;


--
-- Name: deal_item; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deal_item (
    id bigint NOT NULL,
    deal_id bigint NOT NULL,
    product_name text NOT NULL,
    product_code text,
    is_analog boolean DEFAULT false NOT NULL,
    unit text NOT NULL,
    quantity numeric(18,3) NOT NULL,
    price_per_unit numeric(18,2) NOT NULL,
    total_price numeric(18,2) GENERATED ALWAYS AS ((quantity * price_per_unit)) STORED,
    comment text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    item_type character varying(20) DEFAULT 'товар_кп'::character varying,
    CONSTRAINT chk_item_type CHECK (((item_type)::text = ANY (ARRAY[('материал'::character varying)::text, ('работа'::character varying)::text, ('товар_кп'::character varying)::text])))
);


ALTER TABLE public.deal_item OWNER TO postgres;

--
-- Name: COLUMN deal_item.item_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.deal_item.item_type IS 'Тип позиции: материал (из проектной документации), работа (из проектной документации), товар_кп (для формирования КП из БД)';


--
-- Name: deal_item_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.deal_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deal_item_id_seq OWNER TO postgres;

--
-- Name: deal_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.deal_item_id_seq OWNED BY public.deal_item.id;


--
-- Name: document_processing_queue; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.document_processing_queue (
    id integer NOT NULL,
    contract_reg_number character varying(255) NOT NULL,
    table_source character varying(255) NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying,
    worker_id integer,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    error_message text,
    created_at timestamp without time zone DEFAULT now(),
    user_id integer DEFAULT 4,
    priority integer DEFAULT 0
);


ALTER TABLE public.document_processing_queue OWNER TO postgres;

--
-- Name: document_processing_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.document_processing_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.document_processing_queue_id_seq OWNER TO postgres;

--
-- Name: document_processing_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.document_processing_queue_id_seq OWNED BY public.document_processing_queue.id;


--
-- Name: document_stop_phrases; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.document_stop_phrases (
    id integer NOT NULL,
    user_id integer NOT NULL,
    phrase text NOT NULL,
    setting_id integer,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.document_stop_phrases OWNER TO postgres;

--
-- Name: document_stop_phrases_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.document_stop_phrases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.document_stop_phrases_id_seq OWNER TO postgres;

--
-- Name: document_stop_phrases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.document_stop_phrases_id_seq OWNED BY public.document_stop_phrases.id;


--
-- Name: dpq_error_reclass_backup_20260723; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.dpq_error_reclass_backup_20260723 (
    id integer,
    contract_reg_number character varying(255),
    table_source character varying(255),
    status character varying(50),
    worker_id integer,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    error_message text,
    created_at timestamp without time zone,
    user_id integer,
    priority integer
);


ALTER TABLE public.dpq_error_reclass_backup_20260723 OWNER TO postgres;

--
-- Name: expertise_tender_window_score; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.expertise_tender_window_score (
    id integer NOT NULL,
    expertise_id integer NOT NULL,
    expertise_number text,
    subject_rf_code text,
    conclusion_date date,
    segment text,
    object_text text,
    window_start date NOT NULL,
    window_center date NOT NULL,
    window_end date NOT NULL,
    lag_days_assumed integer DEFAULT 240 NOT NULL,
    status text NOT NULL,
    matched_tender_table text,
    matched_tender_id integer,
    matched_tender_number text,
    matched_tender_start date,
    observed_lag_days integer,
    plan_position_id integer,
    plan_publish_year integer,
    plan_finance_total numeric(18,2),
    score numeric(5,3) NOT NULL,
    scored_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.expertise_tender_window_score OWNER TO postgres;

--
-- Name: expertise_tender_window_score_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.expertise_tender_window_score_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.expertise_tender_window_score_id_seq OWNER TO postgres;

--
-- Name: expertise_tender_window_score_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.expertise_tender_window_score_id_seq OWNED BY public.expertise_tender_window_score.id;


--
-- Name: file_names_xml; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.file_names_xml (
    id integer NOT NULL,
    file_name text NOT NULL,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.file_names_xml OWNER TO postgres;

--
-- Name: file_names_xml_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.file_names_xml_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.file_names_xml_id_seq OWNER TO postgres;

--
-- Name: file_names_xml_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.file_names_xml_id_seq OWNED BY public.file_names_xml.id;


--
-- Name: integrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.integrations (
    id bigint NOT NULL,
    integration_type character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    is_active boolean NOT NULL,
    settings jsonb NOT NULL,
    external_id character varying(255) NOT NULL,
    metadata jsonb NOT NULL,
    last_synced_at timestamp with time zone,
    last_error text NOT NULL,
    last_error_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.integrations OWNER TO postgres;

--
-- Name: integrations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.integrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.integrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.invoices (
    id bigint NOT NULL,
    invoice_number character varying(100) NOT NULL,
    file_url character varying(200) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    payment_id bigint NOT NULL
);


ALTER TABLE public.invoices OWNER TO postgres;

--
-- Name: invoices_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.invoices ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.invoices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: key_words_names; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.key_words_names (
    id integer NOT NULL,
    user_id integer,
    key_word text NOT NULL
);


ALTER TABLE public.key_words_names OWNER TO postgres;

--
-- Name: key_words_names_documentations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.key_words_names_documentations (
    id integer NOT NULL,
    user_id integer,
    key_word text NOT NULL,
    setting_id integer
);


ALTER TABLE public.key_words_names_documentations OWNER TO postgres;

--
-- Name: key_words_names_documentations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.key_words_names_documentations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.key_words_names_documentations_id_seq OWNER TO postgres;

--
-- Name: key_words_names_documentations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.key_words_names_documentations_id_seq OWNED BY public.key_words_names_documentations.id;


--
-- Name: key_words_names_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.key_words_names_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.key_words_names_id_seq OWNER TO postgres;

--
-- Name: key_words_names_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.key_words_names_id_seq OWNED BY public.key_words_names.id;


--
-- Name: learning_materials; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.learning_materials (
    id bigint NOT NULL,
    title character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text NOT NULL,
    content text NOT NULL,
    material_type character varying(20) NOT NULL,
    difficulty character varying(20) NOT NULL,
    category character varying(100) NOT NULL,
    tags jsonb NOT NULL,
    thumbnail_url character varying(200) NOT NULL,
    video_url character varying(200) NOT NULL,
    duration_minutes integer,
    author character varying(255) NOT NULL,
    views_count integer NOT NULL,
    rating numeric(3,2) NOT NULL,
    is_featured boolean NOT NULL,
    is_published boolean NOT NULL,
    priority integer NOT NULL,
    related_problems jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    published_at timestamp with time zone
);


ALTER TABLE public.learning_materials OWNER TO postgres;

--
-- Name: learning_materials_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.learning_materials ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.learning_materials_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: links_documentation_223_fz; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.links_documentation_223_fz (
    id integer NOT NULL,
    contract_id integer,
    document_links text NOT NULL,
    file_name text,
    contract_number text
);


ALTER TABLE public.links_documentation_223_fz OWNER TO postgres;

--
-- Name: links_documentation_223_fz_archive; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.links_documentation_223_fz_archive (
    id integer NOT NULL,
    contract_id integer,
    document_links text NOT NULL,
    file_name text,
    contract_number text,
    archived_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_reason text
);


ALTER TABLE public.links_documentation_223_fz_archive OWNER TO postgres;

--
-- Name: links_documentation_223_fz_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.links_documentation_223_fz_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.links_documentation_223_fz_id_seq OWNER TO postgres;

--
-- Name: links_documentation_223_fz_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.links_documentation_223_fz_id_seq OWNED BY public.links_documentation_223_fz.id;


--
-- Name: links_documentation_44_fz; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.links_documentation_44_fz (
    id integer NOT NULL,
    contract_id integer,
    document_links text NOT NULL,
    file_name text,
    contract_number text
);


ALTER TABLE public.links_documentation_44_fz OWNER TO postgres;

--
-- Name: links_documentation_44_fz_archive; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.links_documentation_44_fz_archive (
    id integer NOT NULL,
    contract_id integer,
    document_links text NOT NULL,
    file_name text,
    contract_number text,
    archived_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_reason text
);


ALTER TABLE public.links_documentation_44_fz_archive OWNER TO postgres;

--
-- Name: links_documentation_44_fz_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.links_documentation_44_fz_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.links_documentation_44_fz_id_seq OWNER TO postgres;

--
-- Name: links_documentation_44_fz_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.links_documentation_44_fz_id_seq OWNED BY public.links_documentation_44_fz.id;


--
-- Name: links_documentation_615_pp; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.links_documentation_615_pp (
    id integer NOT NULL,
    contract_id integer,
    document_links text NOT NULL,
    file_name text
);


ALTER TABLE public.links_documentation_615_pp OWNER TO postgres;

--
-- Name: links_documentation_615_pp_commission_work; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.links_documentation_615_pp_commission_work (
    id integer NOT NULL,
    contract_id integer,
    document_links text NOT NULL,
    file_name text
);


ALTER TABLE public.links_documentation_615_pp_commission_work OWNER TO postgres;

--
-- Name: links_documentation_615_pp_commission_work_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.links_documentation_615_pp_commission_work_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.links_documentation_615_pp_commission_work_id_seq OWNER TO postgres;

--
-- Name: links_documentation_615_pp_commission_work_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.links_documentation_615_pp_commission_work_id_seq OWNED BY public.links_documentation_615_pp_commission_work.id;


--
-- Name: links_documentation_615_pp_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.links_documentation_615_pp_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.links_documentation_615_pp_id_seq OWNER TO postgres;

--
-- Name: links_documentation_615_pp_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.links_documentation_615_pp_id_seq OWNED BY public.links_documentation_615_pp.id;


--
-- Name: mfa_backup_codes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mfa_backup_codes (
    id bigint NOT NULL,
    code_hash character varying(255) NOT NULL,
    is_used boolean NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.mfa_backup_codes OWNER TO postgres;

--
-- Name: mfa_backup_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.mfa_backup_codes ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.mfa_backup_codes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mfa_devices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mfa_devices (
    id bigint NOT NULL,
    device_type character varying(10) NOT NULL,
    name character varying(100) NOT NULL,
    secret_key text NOT NULL,
    phone_number text NOT NULL,
    is_active boolean NOT NULL,
    is_primary boolean NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.mfa_devices OWNER TO postgres;

--
-- Name: mfa_devices_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.mfa_devices ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.mfa_devices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notifications (
    id bigint NOT NULL,
    notification_type character varying(50) NOT NULL,
    title character varying(255) NOT NULL,
    message text NOT NULL,
    is_read boolean NOT NULL,
    read_at timestamp with time zone,
    action_url character varying(200) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    related_participation_id bigint,
    related_tender_id bigint,
    user_id bigint NOT NULL
);


ALTER TABLE public.notifications OWNER TO postgres;

--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.notifications ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: okpd_categories; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.okpd_categories (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.okpd_categories OWNER TO postgres;

--
-- Name: okpd_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.okpd_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.okpd_categories_id_seq OWNER TO postgres;

--
-- Name: okpd_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.okpd_categories_id_seq OWNED BY public.okpd_categories.id;


--
-- Name: okpd_from_users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.okpd_from_users (
    id integer NOT NULL,
    user_id integer,
    okpd_code character varying(255),
    name text,
    setting_id integer,
    category_id integer
);


ALTER TABLE public.okpd_from_users OWNER TO postgres;

--
-- Name: okpd_from_users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.okpd_from_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.okpd_from_users_id_seq OWNER TO postgres;

--
-- Name: okpd_from_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.okpd_from_users_id_seq OWNED BY public.okpd_from_users.id;


--
-- Name: onboarding_progress; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.onboarding_progress (
    id bigint NOT NULL,
    current_step integer NOT NULL,
    user_type character varying(50) NOT NULL,
    experience_level character varying(50) NOT NULL,
    industry character varying(100) NOT NULL,
    company_name_onboarding character varying(255) NOT NULL,
    inn_onboarding character varying(20) NOT NULL,
    ogrn_onboarding character varying(20) NOT NULL,
    sro_file character varying(100),
    terms_accepted boolean NOT NULL,
    onboarding_data jsonb NOT NULL,
    is_completed boolean NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.onboarding_progress OWNER TO postgres;

--
-- Name: onboarding_progress_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.onboarding_progress ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.onboarding_progress_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: parser_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.parser_logs (
    id bigint NOT NULL,
    platform character varying(100) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    tenders_found integer NOT NULL,
    tenders_added integer NOT NULL,
    tenders_updated integer NOT NULL,
    errors_count integer NOT NULL,
    status character varying(20) NOT NULL,
    error_message text NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.parser_logs OWNER TO postgres;

--
-- Name: parser_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.parser_logs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.parser_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: participation_status_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.participation_status_history (
    id bigint NOT NULL,
    old_status character varying(20),
    new_status character varying(20) NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    changed_by_type character varying(20) NOT NULL,
    reason text NOT NULL,
    reason_category character varying(20),
    source_data jsonb NOT NULL,
    changed_by_id bigint,
    participation_id bigint NOT NULL
);


ALTER TABLE public.participation_status_history OWNER TO postgres;

--
-- Name: participation_status_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.participation_status_history ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.participation_status_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: payments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payments (
    id bigint NOT NULL,
    amount numeric(15,2) NOT NULL,
    currency character varying(3) NOT NULL,
    payment_method character varying(20) NOT NULL,
    yookassa_payment_id character varying(255),
    status character varying(20) NOT NULL,
    paid_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    subscription_id bigint NOT NULL,
    metadata jsonb NOT NULL
);


ALTER TABLE public.payments OWNER TO postgres;

--
-- Name: payments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.payments ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.payments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: processed_documents; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.processed_documents (
    id bigint NOT NULL,
    tender_id bigint NOT NULL,
    table_source text NOT NULL,
    file_name text NOT NULL,
    status text NOT NULL,
    is_interesting boolean,
    worker_id integer,
    worker_host text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_message text,
    progress_cursor integer DEFAULT 0,
    yandex_path text,
    resume_attempts integer DEFAULT 0,
    last_resume_cursor integer
);


ALTER TABLE public.processed_documents OWNER TO postgres;

--
-- Name: processed_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.processed_documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.processed_documents_id_seq OWNER TO postgres;

--
-- Name: processed_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.processed_documents_id_seq OWNED BY public.processed_documents.id;


--
-- Name: processed_files; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.processed_files (
    id integer NOT NULL,
    tender_id integer NOT NULL,
    registry_type character varying(10) NOT NULL,
    file_path text NOT NULL,
    file_name character varying(255) NOT NULL,
    file_size bigint,
    processing_status character varying(50) DEFAULT 'completed'::character varying NOT NULL,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    error_message text,
    machine_id character varying(100),
    user_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.processed_files OWNER TO postgres;

--
-- Name: TABLE processed_files; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.processed_files IS 'Таблица обработанных файлов для отслеживания прогресса';


--
-- Name: COLUMN processed_files.file_size; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.processed_files.file_size IS 'Размер файла в байтах для статистики';


--
-- Name: processed_files_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.processed_files_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.processed_files_id_seq OWNER TO postgres;

--
-- Name: processed_files_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.processed_files_id_seq OWNED BY public.processed_files.id;


--
-- Name: processed_tenders; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.processed_tenders (
    id integer NOT NULL,
    tender_id integer NOT NULL,
    registry_type character varying(10) NOT NULL,
    folder_name character varying(255) NOT NULL,
    processing_status character varying(50) DEFAULT 'completed'::character varying NOT NULL,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    error_message text,
    machine_id character varying(100),
    user_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.processed_tenders OWNER TO postgres;

--
-- Name: TABLE processed_tenders; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.processed_tenders IS 'Таблица обработанных торгов для предотвращения повторной обработки';


--
-- Name: COLUMN processed_tenders.machine_id; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.processed_tenders.machine_id IS 'ID машины для поддержки параллельной обработки на разных серверах';


--
-- Name: processed_tenders_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.processed_tenders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.processed_tenders_id_seq OWNER TO postgres;

--
-- Name: processed_tenders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.processed_tenders_id_seq OWNED BY public.processed_tenders.id;


--
-- Name: push_subscriptions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.push_subscriptions (
    id bigint NOT NULL,
    endpoint character varying(512) NOT NULL,
    p256dh character varying(255) NOT NULL,
    auth character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.push_subscriptions OWNER TO postgres;

--
-- Name: push_subscriptions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.push_subscriptions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.push_subscriptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reestr_contract_223_fz; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_223_fz (
    id integer NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer NOT NULL,
    contractor_id integer,
    trading_platform_id integer NOT NULL,
    okpd_id integer NOT NULL,
    delivery_region text,
    delivery_address text,
    region_id integer NOT NULL,
    placer text,
    placer_inn text,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_223_fz OWNER TO postgres;

--
-- Name: reestr_contract_223_fz_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.reestr_contract_223_fz_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reestr_contract_223_fz_id_seq OWNER TO postgres;

--
-- Name: reestr_contract_223_fz_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.reestr_contract_223_fz_id_seq OWNED BY public.reestr_contract_223_fz.id;


--
-- Name: reestr_contract_223_fz_awarded; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_223_fz_awarded (
    id integer DEFAULT nextval('public.reestr_contract_223_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer NOT NULL,
    contractor_id integer,
    trading_platform_id integer NOT NULL,
    okpd_id integer NOT NULL,
    delivery_region text,
    delivery_address text,
    region_id integer NOT NULL,
    placer text,
    placer_inn text,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_223_fz_awarded OWNER TO postgres;

--
-- Name: reestr_contract_223_fz_commission_work; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_223_fz_commission_work (
    id integer DEFAULT nextval('public.reestr_contract_223_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer NOT NULL,
    contractor_id integer,
    trading_platform_id integer NOT NULL,
    okpd_id integer NOT NULL,
    delivery_region text,
    delivery_address text,
    region_id integer NOT NULL,
    placer text,
    placer_inn text,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_223_fz_commission_work OWNER TO postgres;

--
-- Name: reestr_contract_223_fz_completed; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_223_fz_completed (
    id integer DEFAULT nextval('public.reestr_contract_223_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer NOT NULL,
    contractor_id integer,
    trading_platform_id integer NOT NULL,
    okpd_id integer NOT NULL,
    delivery_region text,
    delivery_address text,
    region_id integer NOT NULL,
    placer text,
    placer_inn text,
    status_id integer,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


ALTER TABLE public.reestr_contract_223_fz_completed OWNER TO postgres;

--
-- Name: reestr_contract_223_fz_unclear; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_223_fz_unclear (
    id integer DEFAULT nextval('public.reestr_contract_223_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer NOT NULL,
    contractor_id integer,
    trading_platform_id integer NOT NULL,
    okpd_id integer NOT NULL,
    delivery_region text,
    delivery_address text,
    region_id integer NOT NULL,
    placer text,
    placer_inn text,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_223_fz_unclear OWNER TO postgres;

--
-- Name: reestr_contract_44_fz; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz (
    id integer NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_44_fz OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.reestr_contract_44_fz_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reestr_contract_44_fz_id_seq OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.reestr_contract_44_fz_id_seq OWNED BY public.reestr_contract_44_fz.id;


--
-- Name: reestr_contract_44_fz_awarded; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz_awarded (
    id integer DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_44_fz_awarded OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_bad; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz_bad (
    id integer DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer
);


ALTER TABLE public.reestr_contract_44_fz_bad OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_commission_work; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz_commission_work (
    id integer DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_44_fz_commission_work OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_completed; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz_completed (
    id integer DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer
);


ALTER TABLE public.reestr_contract_44_fz_completed OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_unclear; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz_unclear (
    id integer DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.reestr_contract_44_fz_unclear OWNER TO postgres;

--
-- Name: reestr_contract_44_fz_unknown; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_44_fz_unknown (
    id integer DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass) NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer
);


ALTER TABLE public.reestr_contract_44_fz_unknown OWNER TO postgres;

--
-- Name: reestr_contract_615_pp; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_615_pp (
    id integer NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer,
    work_kind_code text,
    work_kind_name text,
    is_waterproofing boolean DEFAULT false,
    matched_keywords text
);


ALTER TABLE public.reestr_contract_615_pp OWNER TO postgres;

--
-- Name: reestr_contract_615_pp_commission_work; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_615_pp_commission_work (
    id integer NOT NULL,
    contract_number text NOT NULL,
    tender_link text NOT NULL,
    start_date date,
    end_date date,
    delivery_start_date date,
    delivery_end_date date,
    auction_name text NOT NULL,
    initial_price numeric NOT NULL,
    final_price numeric,
    guarantee_amount numeric,
    customer_id integer,
    contractor_id integer,
    trading_platform_id integer,
    okpd_id integer,
    customer text,
    warranty_size numeric,
    delivery_region text,
    delivery_address text,
    region_id integer,
    status_id integer,
    work_kind_code text,
    work_kind_name text,
    is_waterproofing boolean DEFAULT false,
    matched_keywords text
);


ALTER TABLE public.reestr_contract_615_pp_commission_work OWNER TO postgres;

--
-- Name: reestr_contract_615_pp_commission_work_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.reestr_contract_615_pp_commission_work_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reestr_contract_615_pp_commission_work_id_seq OWNER TO postgres;

--
-- Name: reestr_contract_615_pp_commission_work_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.reestr_contract_615_pp_commission_work_id_seq OWNED BY public.reestr_contract_615_pp_commission_work.id;


--
-- Name: reestr_contract_615_pp_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.reestr_contract_615_pp_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reestr_contract_615_pp_id_seq OWNER TO postgres;

--
-- Name: reestr_contract_615_pp_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.reestr_contract_615_pp_id_seq OWNED BY public.reestr_contract_615_pp.id;


--
-- Name: reestr_contract_615_pp_nspd_match; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reestr_contract_615_pp_nspd_match (
    id integer NOT NULL,
    contract_id integer NOT NULL,
    cadastral_object_id bigint,
    cadastral_number text,
    object_address text,
    management_company_id bigint,
    uk_name text,
    uk_inn text,
    uk_ogrn text,
    mk_address text,
    match_method text NOT NULL,
    match_score numeric(5,3) NOT NULL,
    street_norm text,
    house_norm text,
    corpus_norm text,
    is_ambiguous boolean DEFAULT false NOT NULL,
    candidates_count integer DEFAULT 1 NOT NULL,
    matched_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.reestr_contract_615_pp_nspd_match OWNER TO postgres;

--
-- Name: reestr_contract_615_pp_nspd_match_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.reestr_contract_615_pp_nspd_match_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reestr_contract_615_pp_nspd_match_id_seq OWNER TO postgres;

--
-- Name: reestr_contract_615_pp_nspd_match_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.reestr_contract_615_pp_nspd_match_id_seq OWNED BY public.reestr_contract_615_pp_nspd_match.id;


--
-- Name: region; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.region (
    id integer NOT NULL,
    code character varying(2) NOT NULL,
    name text NOT NULL
);


ALTER TABLE public.region OWNER TO postgres;

--
-- Name: region_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.region_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.region_id_seq OWNER TO postgres;

--
-- Name: region_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.region_id_seq OWNED BY public.region.id;


--
-- Name: route_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.route_history (
    id bigint NOT NULL,
    from_address character varying(500) NOT NULL,
    from_lat numeric(9,6),
    from_lon numeric(9,6),
    to_address character varying(500) NOT NULL,
    to_lat numeric(9,6),
    to_lon numeric(9,6),
    travel_time_minutes integer NOT NULL,
    travel_mode character varying(20) NOT NULL,
    date_time timestamp with time zone NOT NULL,
    traffic_factor numeric(5,2),
    distance_km numeric(10,2),
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.route_history OWNER TO postgres;

--
-- Name: route_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.route_history ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.route_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: sales_deals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sales_deals (
    id integer NOT NULL,
    pipeline_type character varying(50) NOT NULL,
    stage_id integer NOT NULL,
    tender_id integer,
    name character varying(255) NOT NULL,
    description text,
    amount numeric(15,2),
    margin numeric(10,2),
    status character varying(20) DEFAULT 'active'::character varying,
    tender_status_id integer,
    user_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    metadata jsonb
);


ALTER TABLE public.sales_deals OWNER TO postgres;

--
-- Name: sales_deals_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sales_deals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sales_deals_id_seq OWNER TO postgres;

--
-- Name: sales_deals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sales_deals_id_seq OWNED BY public.sales_deals.id;


--
-- Name: sales_pipeline_stages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sales_pipeline_stages (
    id integer NOT NULL,
    pipeline_type character varying(50) NOT NULL,
    stage_order integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.sales_pipeline_stages OWNER TO postgres;

--
-- Name: sales_pipeline_stages_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sales_pipeline_stages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sales_pipeline_stages_id_seq OWNER TO postgres;

--
-- Name: sales_pipeline_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sales_pipeline_stages_id_seq OWNED BY public.sales_pipeline_stages.id;


--
-- Name: saved_searches; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.saved_searches (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    filters jsonb NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL,
    check_frequency character varying(20) NOT NULL,
    last_check_at timestamp with time zone,
    last_notified_at timestamp with time zone,
    max_notifications_per_day integer NOT NULL,
    notification_channels jsonb NOT NULL,
    notify_on_new boolean NOT NULL,
    query character varying(500) NOT NULL,
    total_matches integer NOT NULL,
    total_notifications_sent integer NOT NULL
);


ALTER TABLE public.saved_searches OWNER TO postgres;

--
-- Name: saved_searches_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.saved_searches ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.saved_searches_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: server_metrics; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.server_metrics (
    id bigint NOT NULL,
    server_id integer NOT NULL,
    recorded_at timestamp without time zone DEFAULT now(),
    cpu_temp smallint,
    gpu_temp smallint,
    ram_used_mb integer,
    ram_total_mb integer,
    load_1min numeric(5,2),
    load_5min numeric(5,2),
    cpu_pct smallint
);


ALTER TABLE public.server_metrics OWNER TO postgres;

--
-- Name: server_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.server_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.server_metrics_id_seq OWNER TO postgres;

--
-- Name: server_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.server_metrics_id_seq OWNED BY public.server_metrics.id;


--
-- Name: setting_options_from_users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.setting_options_from_users (
    id integer NOT NULL,
    name text NOT NULL
);


ALTER TABLE public.setting_options_from_users OWNER TO postgres;

--
-- Name: setting_options_from_users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.setting_options_from_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.setting_options_from_users_id_seq OWNER TO postgres;

--
-- Name: setting_options_from_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.setting_options_from_users_id_seq OWNED BY public.setting_options_from_users.id;


--
-- Name: silk_profile; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.silk_profile (
    id integer NOT NULL,
    name character varying(300) NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone,
    time_taken double precision,
    file_path character varying(300) NOT NULL,
    line_num integer,
    end_line_num integer,
    func_name character varying(300) NOT NULL,
    exception_raised boolean NOT NULL,
    dynamic boolean NOT NULL,
    request_id character varying(36)
);


ALTER TABLE public.silk_profile OWNER TO postgres;

--
-- Name: silk_profile_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.silk_profile ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.silk_profile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: silk_profile_queries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.silk_profile_queries (
    id bigint NOT NULL,
    profile_id integer NOT NULL,
    sqlquery_id integer NOT NULL
);


ALTER TABLE public.silk_profile_queries OWNER TO postgres;

--
-- Name: silk_profile_queries_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.silk_profile_queries ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.silk_profile_queries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: silk_request; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.silk_request (
    id character varying(36) NOT NULL,
    path character varying(190) NOT NULL,
    query_params text NOT NULL,
    raw_body text NOT NULL,
    body text NOT NULL,
    method character varying(10) NOT NULL,
    start_time timestamp with time zone NOT NULL,
    view_name character varying(190),
    end_time timestamp with time zone,
    time_taken double precision,
    encoded_headers text NOT NULL,
    meta_time double precision,
    meta_num_queries integer,
    meta_time_spent_queries double precision,
    pyprofile text NOT NULL,
    num_sql_queries integer NOT NULL,
    prof_file character varying(300) NOT NULL
);


ALTER TABLE public.silk_request OWNER TO postgres;

--
-- Name: silk_response; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.silk_response (
    id character varying(36) NOT NULL,
    status_code integer NOT NULL,
    raw_body text NOT NULL,
    body text NOT NULL,
    encoded_headers text NOT NULL,
    request_id character varying(36) NOT NULL
);


ALTER TABLE public.silk_response OWNER TO postgres;

--
-- Name: silk_sqlquery; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.silk_sqlquery (
    id integer NOT NULL,
    query text NOT NULL,
    start_time timestamp with time zone,
    end_time timestamp with time zone,
    time_taken double precision,
    traceback text NOT NULL,
    request_id character varying(36),
    identifier integer NOT NULL,
    analysis text
);


ALTER TABLE public.silk_sqlquery OWNER TO postgres;

--
-- Name: silk_sqlquery_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.silk_sqlquery ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.silk_sqlquery_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: stop_words_names; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stop_words_names (
    id integer NOT NULL,
    user_id integer,
    stop_word text NOT NULL,
    setting_id integer
);


ALTER TABLE public.stop_words_names OWNER TO postgres;

--
-- Name: stop_words_names_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.stop_words_names_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.stop_words_names_id_seq OWNER TO postgres;

--
-- Name: stop_words_names_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.stop_words_names_id_seq OWNED BY public.stop_words_names.id;


--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.subscriptions (
    id bigint NOT NULL,
    plan_id character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    cancelled_at timestamp with time zone,
    yookassa_subscription_id character varying(255),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.subscriptions OWNER TO postgres;

--
-- Name: subscriptions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.subscriptions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.subscriptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: team_members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.team_members (
    id bigint NOT NULL,
    role character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    joined_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    member_id bigint NOT NULL,
    team_id bigint NOT NULL
);


ALTER TABLE public.team_members OWNER TO postgres;

--
-- Name: team_members_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.team_members ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.team_members_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: teams; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.teams (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    owner_id bigint NOT NULL
);


ALTER TABLE public.teams OWNER TO postgres;

--
-- Name: teams_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.teams ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.teams_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tender_document_match_details; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tender_document_match_details (
    id integer NOT NULL,
    match_id integer NOT NULL,
    product_name text NOT NULL,
    score numeric(5,2) DEFAULT 0.0 NOT NULL,
    sheet_name text,
    row_index integer,
    column_letter text,
    cell_address text,
    source_file text,
    matched_text text,
    matched_display_text text,
    matched_keywords text[],
    row_data jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    line_number integer
);


ALTER TABLE public.tender_document_match_details OWNER TO postgres;

--
-- Name: tender_document_match_details_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tender_document_match_details_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tender_document_match_details_id_seq OWNER TO postgres;

--
-- Name: tender_document_match_details_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tender_document_match_details_id_seq OWNED BY public.tender_document_match_details.id;


--
-- Name: tender_document_matches; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tender_document_matches (
    id integer NOT NULL,
    tender_id integer NOT NULL,
    registry_type character varying(255) NOT NULL,
    match_count integer DEFAULT 0 NOT NULL,
    match_percentage numeric(5,2) DEFAULT 0.00 NOT NULL,
    is_interesting boolean,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    processing_time_seconds numeric(10,2),
    total_files_processed integer DEFAULT 0,
    total_size_bytes bigint DEFAULT 0,
    has_error boolean DEFAULT false,
    error_reason text,
    folder_name text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    worker_id character varying(50),
    status character varying(50),
    file_name text,
    yandex_path text
);


ALTER TABLE public.tender_document_matches OWNER TO postgres;

--
-- Name: TABLE tender_document_matches; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.tender_document_matches IS 'Результаты поиска совпадений товаров в документации торгов';


--
-- Name: COLUMN tender_document_matches.tender_id; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.tender_id IS 'ID торга из реестра контрактов';


--
-- Name: COLUMN tender_document_matches.registry_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.registry_type IS 'Тип реестра: 44fz или 223fz';


--
-- Name: COLUMN tender_document_matches.match_count; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.match_count IS 'Количество найденных совпадений товаров';


--
-- Name: COLUMN tender_document_matches.match_percentage; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.match_percentage IS 'Процент совпадений: 100.00 = 100%, 85.00 = 85%, 0.00 = не обработано';


--
-- Name: COLUMN tender_document_matches.is_interesting; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.is_interesting IS 'Флаг интересности торга для пользователя';


--
-- Name: COLUMN tender_document_matches.processed_at; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.processed_at IS 'Дата и время обработки документов';


--
-- Name: COLUMN tender_document_matches.processing_time_seconds; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.processing_time_seconds IS 'Время обработки в секундах';


--
-- Name: COLUMN tender_document_matches.total_files_processed; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.total_files_processed IS 'Общее количество обработанных файлов';


--
-- Name: COLUMN tender_document_matches.total_size_bytes; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.total_size_bytes IS 'Общий размер обработанных файлов в байтах';


--
-- Name: COLUMN tender_document_matches.has_error; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.has_error IS 'Флаг наличия ошибки обработки торга';


--
-- Name: COLUMN tender_document_matches.error_reason; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.error_reason IS 'Краткая причина ошибки обработки торга';


--
-- Name: COLUMN tender_document_matches.folder_name; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.folder_name IS 'Имя папки с документами торга на файловой системе';


--
-- Name: COLUMN tender_document_matches.created_at; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.created_at IS 'Дата/время создания записи';


--
-- Name: COLUMN tender_document_matches.updated_at; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tender_document_matches.updated_at IS 'Дата/время последнего обновления записи';


--
-- Name: tender_document_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tender_document_matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tender_document_matches_id_seq OWNER TO postgres;

--
-- Name: tender_document_matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tender_document_matches_id_seq OWNED BY public.tender_document_matches.id;


--
-- Name: tender_plan_2020; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tender_plan_2020 (
    id integer NOT NULL,
    eis_id integer,
    eis_external_id integer,
    plan_number text NOT NULL,
    version_number integer DEFAULT 1 NOT NULL,
    plan_year integer,
    period_first_year integer,
    period_second_year integer,
    create_date timestamp without time zone,
    confirm_date timestamp without time zone,
    publish_date timestamp without time zone,
    customer_reg_num text,
    customer_inn text,
    customer_kpp text,
    customer_full_name text,
    customer_oktmo text,
    customer_id integer,
    region_code integer,
    region_id integer,
    source_date date NOT NULL,
    loaded_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tender_plan_2020 OWNER TO postgres;

--
-- Name: tender_plan_2020_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tender_plan_2020_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tender_plan_2020_id_seq OWNER TO postgres;

--
-- Name: tender_plan_2020_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tender_plan_2020_id_seq OWNED BY public.tender_plan_2020.id;


--
-- Name: tender_plan_2020_position; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tender_plan_2020_position (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    position_number text,
    ext_number text,
    ikz text,
    iku text,
    purchase_number text,
    publish_year integer,
    purchase_object text,
    okpd2_code text,
    okpd2_id integer,
    finance_total numeric(18,2),
    finance_current_year numeric(18,2),
    finance_first_year numeric(18,2),
    finance_second_year numeric(18,2),
    is_canceled boolean DEFAULT false,
    modification_number integer,
    modification_status text,
    contract_44_id integer,
    contract_matched_at timestamp without time zone,
    loaded_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tender_plan_2020_position OWNER TO postgres;

--
-- Name: tender_plan_2020_position_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tender_plan_2020_position_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tender_plan_2020_position_id_seq OWNER TO postgres;

--
-- Name: tender_plan_2020_position_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tender_plan_2020_position_id_seq OWNED BY public.tender_plan_2020_position.id;


--
-- Name: tender_plan_2020_progress; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tender_plan_2020_progress (
    id integer NOT NULL,
    source_date date NOT NULL,
    region_code integer NOT NULL,
    plans_loaded integer DEFAULT 0 NOT NULL,
    positions_loaded integer DEFAULT 0 NOT NULL,
    processed_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tender_plan_2020_progress OWNER TO postgres;

--
-- Name: tender_plan_2020_progress_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tender_plan_2020_progress_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tender_plan_2020_progress_id_seq OWNER TO postgres;

--
-- Name: tender_plan_2020_progress_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tender_plan_2020_progress_id_seq OWNED BY public.tender_plan_2020_progress.id;


--
-- Name: tender_statuses; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tender_statuses (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.tender_statuses OWNER TO postgres;

--
-- Name: tender_statuses_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tender_statuses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tender_statuses_id_seq OWNER TO postgres;

--
-- Name: tender_statuses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tender_statuses_id_seq OWNED BY public.tender_statuses.id;


--
-- Name: tenders; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tenders (
    id integer NOT NULL,
    external_id character varying(255) NOT NULL,
    title character varying(500) NOT NULL,
    description text,
    code character varying(100) NOT NULL,
    tender_number character varying(100) DEFAULT ''::character varying,
    platform character varying(100) NOT NULL,
    customer_name character varying(255) NOT NULL,
    customer_inn character varying(20) NOT NULL,
    customer_contact_email character varying(254),
    customer_contact_phone character varying(20),
    nmck numeric(15,2),
    estimated_price numeric(15,2),
    security_deposit numeric(15,2),
    security_deposit_percent numeric(5,2),
    security_deposit_type character varying(20),
    required_experience_years integer DEFAULT 0,
    required_qualifications text,
    required_licenses text,
    required_certificates text,
    required_sro boolean DEFAULT false,
    region character varying(100) NOT NULL,
    city character varying(100),
    address text,
    published_at timestamp with time zone NOT NULL,
    deadline_at timestamp with time zone NOT NULL,
    category character varying(100) NOT NULL,
    status character varying(20) DEFAULT 'published'::character varying,
    ai_analysis jsonb,
    documents jsonb DEFAULT '[]'::jsonb,
    win_probability real DEFAULT 0.0,
    difficulty_score integer DEFAULT 0,
    participation_count integer DEFAULT 0,
    predicted_competitors integer DEFAULT 0,
    search_vector tsvector,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    parsed_at timestamp with time zone,
    imported_from_platform_at timestamp with time zone,
    okpd2_code character varying(50),
    okpd2_name text
);


ALTER TABLE public.tenders OWNER TO postgres;

--
-- Name: tenders_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenders_id_seq OWNER TO postgres;

--
-- Name: tenders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenders_id_seq OWNED BY public.tenders.id;


--
-- Name: token_blacklist_blacklistedtoken; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.token_blacklist_blacklistedtoken (
    id bigint NOT NULL,
    blacklisted_at timestamp with time zone NOT NULL,
    token_id bigint NOT NULL
);


ALTER TABLE public.token_blacklist_blacklistedtoken OWNER TO postgres;

--
-- Name: token_blacklist_blacklistedtoken_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.token_blacklist_blacklistedtoken ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.token_blacklist_blacklistedtoken_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: token_blacklist_outstandingtoken; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.token_blacklist_outstandingtoken (
    id bigint NOT NULL,
    token text NOT NULL,
    created_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    user_id bigint,
    jti character varying(255) NOT NULL
);


ALTER TABLE public.token_blacklist_outstandingtoken OWNER TO postgres;

--
-- Name: token_blacklist_outstandingtoken_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.token_blacklist_outstandingtoken ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.token_blacklist_outstandingtoken_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trading_platform; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.trading_platform (
    id integer NOT NULL,
    trading_platform_name text NOT NULL,
    trading_platform_url text NOT NULL
);


ALTER TABLE public.trading_platform OWNER TO postgres;

--
-- Name: trading_platform_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.trading_platform_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.trading_platform_id_seq OWNER TO postgres;

--
-- Name: trading_platform_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.trading_platform_id_seq OWNED BY public.trading_platform.id;


--
-- Name: user_achievements; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_achievements (
    id bigint NOT NULL,
    unlocked_at timestamp with time zone NOT NULL,
    achievement_id bigint NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.user_achievements OWNER TO postgres;

--
-- Name: user_achievements_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.user_achievements ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_achievements_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_challenges; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_challenges (
    id bigint NOT NULL,
    current_value integer NOT NULL,
    completed_at timestamp with time zone,
    reward_claimed boolean NOT NULL,
    reward_claimed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    challenge_id bigint NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.user_challenges OWNER TO postgres;

--
-- Name: user_challenges_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.user_challenges ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_challenges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_credentials; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_credentials (
    id bigint NOT NULL,
    credential_type character varying(50) NOT NULL,
    credential_name character varying(255) NOT NULL,
    issued_at date,
    expires_at date,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL,
    file character varying(100),
    is_active boolean NOT NULL,
    issued_by character varying(255) NOT NULL
);


ALTER TABLE public.user_credentials OWNER TO postgres;

--
-- Name: user_credentials_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.user_credentials ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_credentials_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_learning_progress; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_learning_progress (
    id bigint NOT NULL,
    is_completed boolean NOT NULL,
    progress_percent integer NOT NULL,
    time_spent_minutes integer NOT NULL,
    user_rating integer,
    user_comment text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone NOT NULL,
    material_id bigint NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.user_learning_progress OWNER TO postgres;

--
-- Name: user_learning_progress_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.user_learning_progress ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_learning_progress_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_locations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_locations (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    address character varying(500) NOT NULL,
    lat numeric(9,6),
    lon numeric(9,6),
    is_default boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


ALTER TABLE public.user_locations OWNER TO postgres;

--
-- Name: user_locations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.user_locations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_locations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_search_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_search_settings (
    user_id integer NOT NULL,
    region_id integer,
    category_id integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.user_search_settings OWNER TO postgres;

--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    company_name character varying(255) NOT NULL,
    company_type character varying(50) NOT NULL,
    phone character varying(20) NOT NULL,
    inn character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    subscription_tier character varying(20) NOT NULL,
    level integer NOT NULL,
    last_activity_date date,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_login_at timestamp with time zone,
    metadata jsonb NOT NULL,
    preferences jsonb NOT NULL,
    telegram_user_id bigint,
    telegram_username character varying(100) NOT NULL,
    telegram_notifications_enabled boolean NOT NULL,
    total_points integer NOT NULL,
    total_tenders_found integer NOT NULL,
    total_participations integer NOT NULL,
    total_wins integer NOT NULL,
    total_won_amount numeric(15,2) NOT NULL,
    role character varying(20) DEFAULT 'free_user'::character varying,
    xp integer DEFAULT 0,
    reputation_score integer DEFAULT 0
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_blogpost; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users_blogpost (
    id bigint NOT NULL,
    title character varying(200) NOT NULL,
    slug character varying(200) NOT NULL,
    author character varying(100) NOT NULL,
    category character varying(50) NOT NULL,
    excerpt text NOT NULL,
    content text NOT NULL,
    featured_image character varying(100),
    status character varying(20) NOT NULL,
    published_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    views_count integer NOT NULL,
    meta_description character varying(160) NOT NULL,
    meta_keywords character varying(255) NOT NULL,
    CONSTRAINT users_blogpost_views_count_check CHECK ((views_count >= 0))
);


ALTER TABLE public.users_blogpost OWNER TO postgres;

--
-- Name: users_blogpost_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.users_blogpost ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.users_blogpost_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: users_groups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users_groups (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    group_id integer NOT NULL
);


ALTER TABLE public.users_groups OWNER TO postgres;

--
-- Name: users_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.users_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.users_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.users ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: users_user_permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users_user_permissions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.users_user_permissions OWNER TO postgres;

--
-- Name: users_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.users_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.users_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: webinar_registrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.webinar_registrations (
    id bigint NOT NULL,
    attended boolean NOT NULL,
    feedback_rating integer,
    feedback_comment text NOT NULL,
    registered_at timestamp with time zone NOT NULL,
    attended_at timestamp with time zone,
    user_id bigint NOT NULL,
    webinar_id bigint NOT NULL
);


ALTER TABLE public.webinar_registrations OWNER TO postgres;

--
-- Name: webinar_registrations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.webinar_registrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.webinar_registrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: webinars; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.webinars (
    id bigint NOT NULL,
    title character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text NOT NULL,
    expert_name character varying(255) NOT NULL,
    expert_title character varying(255) NOT NULL,
    expert_bio text NOT NULL,
    expert_photo_url character varying(200) NOT NULL,
    scheduled_at timestamp with time zone,
    duration_minutes integer NOT NULL,
    registration_url character varying(200) NOT NULL,
    video_url character varying(200) NOT NULL,
    slides_url character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    category character varying(100) NOT NULL,
    tags jsonb NOT NULL,
    views_count integer NOT NULL,
    registrations_count integer NOT NULL,
    is_featured boolean NOT NULL,
    priority integer NOT NULL,
    related_problems jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.webinars OWNER TO postgres;

--
-- Name: webinars_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.webinars ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.webinars_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: xp_transactions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.xp_transactions (
    id bigint NOT NULL,
    amount integer NOT NULL,
    reason character varying(100) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    related_achievement_id bigint,
    user_id bigint NOT NULL
);


ALTER TABLE public.xp_transactions OWNER TO postgres;

--
-- Name: xp_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.xp_transactions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.xp_transactions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: collection_codes_okpd id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.collection_codes_okpd ALTER COLUMN id SET DEFAULT nextval('public.collection_codes_okpd_id_seq'::regclass);


--
-- Name: contact id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact ALTER COLUMN id SET DEFAULT nextval('public.contact_id_seq'::regclass);


--
-- Name: contact_link id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact_link ALTER COLUMN id SET DEFAULT nextval('public.contact_link_id_seq'::regclass);


--
-- Name: contractor id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contractor ALTER COLUMN id SET DEFAULT nextval('public.contractor_id_seq'::regclass);


--
-- Name: contractor_role id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contractor_role ALTER COLUMN id SET DEFAULT nextval('public.contractor_role_id_seq'::regclass);


--
-- Name: crm_docs_priority_hints id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_docs_priority_hints ALTER COLUMN id SET DEFAULT nextval('public.crm_docs_priority_hints_id_seq'::regclass);


--
-- Name: crm_object_type_classifications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_type_classifications ALTER COLUMN id SET DEFAULT nextval('public.crm_object_type_classifications_id_seq'::regclass);


--
-- Name: crm_unified_object_links id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_object_links ALTER COLUMN id SET DEFAULT nextval('public.crm_unified_object_links_id_seq'::regclass);


--
-- Name: crm_unified_objects id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_objects ALTER COLUMN id SET DEFAULT nextval('public.crm_unified_objects_id_seq'::regclass);


--
-- Name: crm_unified_signals id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_signals ALTER COLUMN id SET DEFAULT nextval('public.crm_unified_signals_id_seq'::regclass);


--
-- Name: customer id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customer ALTER COLUMN id SET DEFAULT nextval('public.customer_id_seq'::regclass);


--
-- Name: customer_role id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customer_role ALTER COLUMN id SET DEFAULT nextval('public.customer_role_id_seq'::regclass);


--
-- Name: dates id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.dates ALTER COLUMN id SET DEFAULT nextval('public.dates_id_seq'::regclass);


--
-- Name: deal_chat id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deal_chat ALTER COLUMN id SET DEFAULT nextval('public.deal_chat_id_seq'::regclass);


--
-- Name: deal_item id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deal_item ALTER COLUMN id SET DEFAULT nextval('public.deal_item_id_seq'::regclass);


--
-- Name: document_processing_queue id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_processing_queue ALTER COLUMN id SET DEFAULT nextval('public.document_processing_queue_id_seq'::regclass);


--
-- Name: document_stop_phrases id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_stop_phrases ALTER COLUMN id SET DEFAULT nextval('public.document_stop_phrases_id_seq'::regclass);


--
-- Name: expertise_tender_window_score id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.expertise_tender_window_score ALTER COLUMN id SET DEFAULT nextval('public.expertise_tender_window_score_id_seq'::regclass);


--
-- Name: file_names_xml id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.file_names_xml ALTER COLUMN id SET DEFAULT nextval('public.file_names_xml_id_seq'::regclass);


--
-- Name: key_words_names id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names ALTER COLUMN id SET DEFAULT nextval('public.key_words_names_id_seq'::regclass);


--
-- Name: key_words_names_documentations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names_documentations ALTER COLUMN id SET DEFAULT nextval('public.key_words_names_documentations_id_seq'::regclass);


--
-- Name: links_documentation_223_fz id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_223_fz ALTER COLUMN id SET DEFAULT nextval('public.links_documentation_223_fz_id_seq'::regclass);


--
-- Name: links_documentation_44_fz id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_44_fz ALTER COLUMN id SET DEFAULT nextval('public.links_documentation_44_fz_id_seq'::regclass);


--
-- Name: links_documentation_615_pp id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_615_pp ALTER COLUMN id SET DEFAULT nextval('public.links_documentation_615_pp_id_seq'::regclass);


--
-- Name: links_documentation_615_pp_commission_work id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_615_pp_commission_work ALTER COLUMN id SET DEFAULT nextval('public.links_documentation_615_pp_commission_work_id_seq'::regclass);


--
-- Name: okpd_categories id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_categories ALTER COLUMN id SET DEFAULT nextval('public.okpd_categories_id_seq'::regclass);


--
-- Name: okpd_from_users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_from_users ALTER COLUMN id SET DEFAULT nextval('public.okpd_from_users_id_seq'::regclass);


--
-- Name: processed_documents id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_documents ALTER COLUMN id SET DEFAULT nextval('public.processed_documents_id_seq'::regclass);


--
-- Name: processed_files id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_files ALTER COLUMN id SET DEFAULT nextval('public.processed_files_id_seq'::regclass);


--
-- Name: processed_tenders id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_tenders ALTER COLUMN id SET DEFAULT nextval('public.processed_tenders_id_seq'::regclass);


--
-- Name: reestr_contract_223_fz id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz ALTER COLUMN id SET DEFAULT nextval('public.reestr_contract_223_fz_id_seq'::regclass);


--
-- Name: reestr_contract_44_fz id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz ALTER COLUMN id SET DEFAULT nextval('public.reestr_contract_44_fz_id_seq'::regclass);


--
-- Name: reestr_contract_615_pp id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp ALTER COLUMN id SET DEFAULT nextval('public.reestr_contract_615_pp_id_seq'::regclass);


--
-- Name: reestr_contract_615_pp_commission_work id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work ALTER COLUMN id SET DEFAULT nextval('public.reestr_contract_615_pp_commission_work_id_seq'::regclass);


--
-- Name: reestr_contract_615_pp_nspd_match id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_nspd_match ALTER COLUMN id SET DEFAULT nextval('public.reestr_contract_615_pp_nspd_match_id_seq'::regclass);


--
-- Name: region id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.region ALTER COLUMN id SET DEFAULT nextval('public.region_id_seq'::regclass);


--
-- Name: sales_deals id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales_deals ALTER COLUMN id SET DEFAULT nextval('public.sales_deals_id_seq'::regclass);


--
-- Name: sales_pipeline_stages id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales_pipeline_stages ALTER COLUMN id SET DEFAULT nextval('public.sales_pipeline_stages_id_seq'::regclass);


--
-- Name: server_metrics id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.server_metrics ALTER COLUMN id SET DEFAULT nextval('public.server_metrics_id_seq'::regclass);


--
-- Name: setting_options_from_users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.setting_options_from_users ALTER COLUMN id SET DEFAULT nextval('public.setting_options_from_users_id_seq'::regclass);


--
-- Name: stop_words_names id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stop_words_names ALTER COLUMN id SET DEFAULT nextval('public.stop_words_names_id_seq'::regclass);


--
-- Name: tender_document_match_details id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_document_match_details ALTER COLUMN id SET DEFAULT nextval('public.tender_document_match_details_id_seq'::regclass);


--
-- Name: tender_document_matches id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_document_matches ALTER COLUMN id SET DEFAULT nextval('public.tender_document_matches_id_seq'::regclass);


--
-- Name: tender_plan_2020 id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020 ALTER COLUMN id SET DEFAULT nextval('public.tender_plan_2020_id_seq'::regclass);


--
-- Name: tender_plan_2020_position id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_position ALTER COLUMN id SET DEFAULT nextval('public.tender_plan_2020_position_id_seq'::regclass);


--
-- Name: tender_plan_2020_progress id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_progress ALTER COLUMN id SET DEFAULT nextval('public.tender_plan_2020_progress_id_seq'::regclass);


--
-- Name: tender_statuses id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_statuses ALTER COLUMN id SET DEFAULT nextval('public.tender_statuses_id_seq'::regclass);


--
-- Name: tenders id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenders ALTER COLUMN id SET DEFAULT nextval('public.tenders_id_seq'::regclass);


--
-- Name: trading_platform id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trading_platform ALTER COLUMN id SET DEFAULT nextval('public.trading_platform_id_seq'::regclass);


--
-- Name: achievements achievements_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.achievements
    ADD CONSTRAINT achievements_code_key UNIQUE (code);


--
-- Name: achievements achievements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.achievements
    ADD CONSTRAINT achievements_pkey PRIMARY KEY (id);


--
-- Name: ai_analysis_logs ai_analysis_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_analysis_logs
    ADD CONSTRAINT ai_analysis_logs_pkey PRIMARY KEY (id);


--
-- Name: ai_quality_metrics ai_quality_metrics_date_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_quality_metrics
    ADD CONSTRAINT ai_quality_metrics_date_key UNIQUE (date);


--
-- Name: ai_quality_metrics ai_quality_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_quality_metrics
    ADD CONSTRAINT ai_quality_metrics_pkey PRIMARY KEY (id);


--
-- Name: ai_validation_reports ai_validation_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_validation_reports
    ADD CONSTRAINT ai_validation_reports_pkey PRIMARY KEY (id);


--
-- Name: analytics_snapshots analytics_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.analytics_snapshots
    ADD CONSTRAINT analytics_snapshots_pkey PRIMARY KEY (id);


--
-- Name: application_forms application_forms_participation_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_forms
    ADD CONSTRAINT application_forms_participation_id_key UNIQUE (participation_id);


--
-- Name: application_forms application_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_forms
    ADD CONSTRAINT application_forms_pkey PRIMARY KEY (id);


--
-- Name: application_templates application_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_templates
    ADD CONSTRAINT application_templates_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: calendar_settings calendar_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.calendar_settings
    ADD CONSTRAINT calendar_settings_pkey PRIMARY KEY (id);


--
-- Name: calendar_settings calendar_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.calendar_settings
    ADD CONSTRAINT calendar_settings_user_id_key UNIQUE (user_id);


--
-- Name: calibration_metrics calibration_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.calibration_metrics
    ADD CONSTRAINT calibration_metrics_pkey PRIMARY KEY (id);


--
-- Name: calibration_weights calibration_weights_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.calibration_weights
    ADD CONSTRAINT calibration_weights_pkey PRIMARY KEY (id);


--
-- Name: calibration_weights calibration_weights_version_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.calibration_weights
    ADD CONSTRAINT calibration_weights_version_key UNIQUE (version);


--
-- Name: challenges challenges_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.challenges
    ADD CONSTRAINT challenges_pkey PRIMARY KEY (id);


--
-- Name: checklist_items checklist_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checklist_items
    ADD CONSTRAINT checklist_items_pkey PRIMARY KEY (id);


--
-- Name: collection_codes_okpd collection_codes_okpd_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.collection_codes_okpd
    ADD CONSTRAINT collection_codes_okpd_pkey PRIMARY KEY (id);


--
-- Name: competitors competitors_identifier_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT competitors_identifier_key UNIQUE (identifier);


--
-- Name: competitors competitors_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT competitors_pkey PRIMARY KEY (id);


--
-- Name: consultations consultations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consultations
    ADD CONSTRAINT consultations_pkey PRIMARY KEY (id);


--
-- Name: contact_link contact_link_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact_link
    ADD CONSTRAINT contact_link_pkey PRIMARY KEY (id);


--
-- Name: contact contact_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact
    ADD CONSTRAINT contact_pkey PRIMARY KEY (id);


--
-- Name: contract_category_scores contract_category_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contract_category_scores
    ADD CONSTRAINT contract_category_scores_pkey PRIMARY KEY (contract_number, category_code);


--
-- Name: contractor contractor_inn_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contractor
    ADD CONSTRAINT contractor_inn_key UNIQUE (inn);


--
-- Name: contractor contractor_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contractor
    ADD CONSTRAINT contractor_pkey PRIMARY KEY (id);


--
-- Name: contractor_role contractor_role_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contractor_role
    ADD CONSTRAINT contractor_role_pkey PRIMARY KEY (id);


--
-- Name: crm_docs_priority_hints crm_docs_priority_hints_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_docs_priority_hints
    ADD CONSTRAINT crm_docs_priority_hints_pkey PRIMARY KEY (id);


--
-- Name: crm_docs_priority_hints crm_docs_priority_hints_tender_id_registry_type_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_docs_priority_hints
    ADD CONSTRAINT crm_docs_priority_hints_tender_id_registry_type_key UNIQUE (tender_id, registry_type);


--
-- Name: crm_object_type_classifications crm_object_type_classifications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_object_type_classifications
    ADD CONSTRAINT crm_object_type_classifications_pkey PRIMARY KEY (id);


--
-- Name: crm_unified_object_links crm_unified_object_links_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_object_links
    ADD CONSTRAINT crm_unified_object_links_pkey PRIMARY KEY (id);


--
-- Name: crm_unified_objects crm_unified_objects_object_uid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_objects
    ADD CONSTRAINT crm_unified_objects_object_uid_key UNIQUE (object_uid);


--
-- Name: crm_unified_objects crm_unified_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_objects
    ADD CONSTRAINT crm_unified_objects_pkey PRIMARY KEY (id);


--
-- Name: crm_unified_signals crm_unified_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crm_unified_signals
    ADD CONSTRAINT crm_unified_signals_pkey PRIMARY KEY (id);


--
-- Name: customer customer_inn_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_inn_key UNIQUE (customer_inn);


--
-- Name: customer customer_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_pkey PRIMARY KEY (id);


--
-- Name: customer_role customer_role_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customer_role
    ADD CONSTRAINT customer_role_pkey PRIMARY KEY (id);


--
-- Name: customers customers_inn_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_inn_key UNIQUE (inn);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);


--
-- Name: daily_quests daily_quests_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_quests
    ADD CONSTRAINT daily_quests_pkey PRIMARY KEY (id);


--
-- Name: dates dates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.dates
    ADD CONSTRAINT dates_pkey PRIMARY KEY (id);


--
-- Name: deadline_events deadline_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deadline_events
    ADD CONSTRAINT deadline_events_pkey PRIMARY KEY (id);


--
-- Name: deal_chat deal_chat_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deal_chat
    ADD CONSTRAINT deal_chat_pkey PRIMARY KEY (id);


--
-- Name: deal_item deal_item_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deal_item
    ADD CONSTRAINT deal_item_pkey PRIMARY KEY (id);


--
-- Name: document_processing_queue document_processing_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_processing_queue
    ADD CONSTRAINT document_processing_queue_pkey PRIMARY KEY (id);


--
-- Name: document_stop_phrases document_stop_phrases_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_stop_phrases
    ADD CONSTRAINT document_stop_phrases_pkey PRIMARY KEY (id);


--
-- Name: expertise_tender_window_score expertise_tender_window_score_expertise_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.expertise_tender_window_score
    ADD CONSTRAINT expertise_tender_window_score_expertise_id_key UNIQUE (expertise_id);


--
-- Name: expertise_tender_window_score expertise_tender_window_score_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.expertise_tender_window_score
    ADD CONSTRAINT expertise_tender_window_score_pkey PRIMARY KEY (id);


--
-- Name: file_names_xml file_names_xml_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.file_names_xml
    ADD CONSTRAINT file_names_xml_pkey PRIMARY KEY (id);


--
-- Name: integrations integrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.integrations
    ADD CONSTRAINT integrations_pkey PRIMARY KEY (id);


--
-- Name: integrations integrations_user_id_integration_type_name_d6f416aa_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.integrations
    ADD CONSTRAINT integrations_user_id_integration_type_name_d6f416aa_uniq UNIQUE (user_id, integration_type, name);


--
-- Name: invoices invoices_invoice_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);


--
-- Name: key_words_names_documentations key_words_names_documentations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names_documentations
    ADD CONSTRAINT key_words_names_documentations_pkey PRIMARY KEY (id);


--
-- Name: key_words_names key_words_names_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names
    ADD CONSTRAINT key_words_names_pkey PRIMARY KEY (id);


--
-- Name: learning_materials learning_materials_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.learning_materials
    ADD CONSTRAINT learning_materials_pkey PRIMARY KEY (id);


--
-- Name: learning_materials learning_materials_slug_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.learning_materials
    ADD CONSTRAINT learning_materials_slug_key UNIQUE (slug);


--
-- Name: links_documentation_223_fz_archive links_documentation_223_fz_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_223_fz_archive
    ADD CONSTRAINT links_documentation_223_fz_archive_pkey PRIMARY KEY (id);


--
-- Name: links_documentation_223_fz links_documentation_223_fz_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_223_fz
    ADD CONSTRAINT links_documentation_223_fz_pkey PRIMARY KEY (id);


--
-- Name: links_documentation_44_fz_archive links_documentation_44_fz_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_44_fz_archive
    ADD CONSTRAINT links_documentation_44_fz_archive_pkey PRIMARY KEY (id);


--
-- Name: links_documentation_44_fz links_documentation_44_fz_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_44_fz
    ADD CONSTRAINT links_documentation_44_fz_pkey PRIMARY KEY (id);


--
-- Name: links_documentation_615_pp_commission_work links_documentation_615_pp_commission_work_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_615_pp_commission_work
    ADD CONSTRAINT links_documentation_615_pp_commission_work_pkey PRIMARY KEY (id);


--
-- Name: links_documentation_615_pp links_documentation_615_pp_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_615_pp
    ADD CONSTRAINT links_documentation_615_pp_pkey PRIMARY KEY (id);


--
-- Name: mfa_backup_codes mfa_backup_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mfa_backup_codes
    ADD CONSTRAINT mfa_backup_codes_pkey PRIMARY KEY (id);


--
-- Name: mfa_devices mfa_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mfa_devices
    ADD CONSTRAINT mfa_devices_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: okpd_categories okpd_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_categories
    ADD CONSTRAINT okpd_categories_pkey PRIMARY KEY (id);


--
-- Name: okpd_from_users okpd_from_users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_from_users
    ADD CONSTRAINT okpd_from_users_pkey PRIMARY KEY (id);


--
-- Name: onboarding_progress onboarding_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.onboarding_progress
    ADD CONSTRAINT onboarding_progress_pkey PRIMARY KEY (id);


--
-- Name: onboarding_progress onboarding_progress_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.onboarding_progress
    ADD CONSTRAINT onboarding_progress_user_id_key UNIQUE (user_id);


--
-- Name: parser_logs parser_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parser_logs
    ADD CONSTRAINT parser_logs_pkey PRIMARY KEY (id);


--
-- Name: participation_status_history participation_status_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation_status_history
    ADD CONSTRAINT participation_status_history_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: payments payments_yookassa_payment_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_yookassa_payment_id_key UNIQUE (yookassa_payment_id);


--
-- Name: processed_documents processed_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_documents
    ADD CONSTRAINT processed_documents_pkey PRIMARY KEY (id);


--
-- Name: processed_documents processed_documents_tender_id_table_source_file_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_documents
    ADD CONSTRAINT processed_documents_tender_id_table_source_file_name_key UNIQUE (tender_id, table_source, file_name);


--
-- Name: processed_files processed_files_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_files
    ADD CONSTRAINT processed_files_pkey PRIMARY KEY (id);


--
-- Name: processed_files processed_files_tender_id_registry_type_file_path_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_files
    ADD CONSTRAINT processed_files_tender_id_registry_type_file_path_key UNIQUE (tender_id, registry_type, file_path);


--
-- Name: processed_tenders processed_tenders_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_tenders
    ADD CONSTRAINT processed_tenders_pkey PRIMARY KEY (id);


--
-- Name: processed_tenders processed_tenders_tender_id_registry_type_folder_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.processed_tenders
    ADD CONSTRAINT processed_tenders_tender_id_registry_type_folder_name_key UNIQUE (tender_id, registry_type, folder_name);


--
-- Name: push_subscriptions push_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: push_subscriptions push_subscriptions_user_id_endpoint_090a714f_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_user_id_endpoint_090a714f_uniq UNIQUE (user_id, endpoint);


--
-- Name: reestr_contract_223_fz_awarded reestr_contract_223_fz_awarded_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz_awarded
    ADD CONSTRAINT reestr_contract_223_fz_awarded_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_223_fz_commission_work reestr_contract_223_fz_commission_work_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz_commission_work
    ADD CONSTRAINT reestr_contract_223_fz_commission_work_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_223_fz_completed reestr_contract_223_fz_completed_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz_completed
    ADD CONSTRAINT reestr_contract_223_fz_completed_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_223_fz reestr_contract_223_fz_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz
    ADD CONSTRAINT reestr_contract_223_fz_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_223_fz_unclear reestr_contract_223_fz_unclear_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz_unclear
    ADD CONSTRAINT reestr_contract_223_fz_unclear_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz_awarded reestr_contract_44_fz_awarded_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz_awarded
    ADD CONSTRAINT reestr_contract_44_fz_awarded_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz_bad reestr_contract_44_fz_bad_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz_bad
    ADD CONSTRAINT reestr_contract_44_fz_bad_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz_commission_work reestr_contract_44_fz_commission_work_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz_commission_work
    ADD CONSTRAINT reestr_contract_44_fz_commission_work_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz_completed reestr_contract_44_fz_completed_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz_completed
    ADD CONSTRAINT reestr_contract_44_fz_completed_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz reestr_contract_44_fz_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz
    ADD CONSTRAINT reestr_contract_44_fz_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz_unclear reestr_contract_44_fz_unclear_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz_unclear
    ADD CONSTRAINT reestr_contract_44_fz_unclear_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_44_fz_unknown reestr_contract_44_fz_unknown_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz_unknown
    ADD CONSTRAINT reestr_contract_44_fz_unknown_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_contract_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_contract_number_key UNIQUE (contract_number);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_contract_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_contract_number_key UNIQUE (contract_number);


--
-- Name: reestr_contract_615_pp_nspd_match reestr_contract_615_pp_nspd_match_contract_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_nspd_match
    ADD CONSTRAINT reestr_contract_615_pp_nspd_match_contract_id_key UNIQUE (contract_id);


--
-- Name: reestr_contract_615_pp_nspd_match reestr_contract_615_pp_nspd_match_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_nspd_match
    ADD CONSTRAINT reestr_contract_615_pp_nspd_match_pkey PRIMARY KEY (id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_pkey PRIMARY KEY (id);


--
-- Name: region region_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.region
    ADD CONSTRAINT region_code_key UNIQUE (code);


--
-- Name: region region_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.region
    ADD CONSTRAINT region_pkey PRIMARY KEY (id);


--
-- Name: route_history route_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.route_history
    ADD CONSTRAINT route_history_pkey PRIMARY KEY (id);


--
-- Name: sales_deals sales_deals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales_deals
    ADD CONSTRAINT sales_deals_pkey PRIMARY KEY (id);


--
-- Name: sales_pipeline_stages sales_pipeline_stages_pipeline_type_stage_order_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales_pipeline_stages
    ADD CONSTRAINT sales_pipeline_stages_pipeline_type_stage_order_key UNIQUE (pipeline_type, stage_order);


--
-- Name: sales_pipeline_stages sales_pipeline_stages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales_pipeline_stages
    ADD CONSTRAINT sales_pipeline_stages_pkey PRIMARY KEY (id);


--
-- Name: saved_searches saved_searches_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.saved_searches
    ADD CONSTRAINT saved_searches_pkey PRIMARY KEY (id);


--
-- Name: server_metrics server_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.server_metrics
    ADD CONSTRAINT server_metrics_pkey PRIMARY KEY (id);


--
-- Name: setting_options_from_users setting_options_from_users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.setting_options_from_users
    ADD CONSTRAINT setting_options_from_users_pkey PRIMARY KEY (id);


--
-- Name: silk_profile silk_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_profile
    ADD CONSTRAINT silk_profile_pkey PRIMARY KEY (id);


--
-- Name: silk_profile_queries silk_profile_queries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_profile_queries
    ADD CONSTRAINT silk_profile_queries_pkey PRIMARY KEY (id);


--
-- Name: silk_profile_queries silk_profile_queries_profile_id_sqlquery_id_b2403d9b_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_profile_queries
    ADD CONSTRAINT silk_profile_queries_profile_id_sqlquery_id_b2403d9b_uniq UNIQUE (profile_id, sqlquery_id);


--
-- Name: silk_request silk_request_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_request
    ADD CONSTRAINT silk_request_pkey PRIMARY KEY (id);


--
-- Name: silk_response silk_response_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_response
    ADD CONSTRAINT silk_response_pkey PRIMARY KEY (id);


--
-- Name: silk_response silk_response_request_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_response
    ADD CONSTRAINT silk_response_request_id_key UNIQUE (request_id);


--
-- Name: silk_sqlquery silk_sqlquery_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_sqlquery
    ADD CONSTRAINT silk_sqlquery_pkey PRIMARY KEY (id);


--
-- Name: stop_words_names stop_words_names_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stop_words_names
    ADD CONSTRAINT stop_words_names_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_yookassa_subscription_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_yookassa_subscription_id_key UNIQUE (yookassa_subscription_id);


--
-- Name: team_members team_members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_pkey PRIMARY KEY (id);


--
-- Name: team_members team_members_team_id_member_id_4c9ef58c_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_team_id_member_id_4c9ef58c_uniq UNIQUE (team_id, member_id);


--
-- Name: teams teams_owner_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_owner_id_key UNIQUE (owner_id);


--
-- Name: teams teams_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);


--
-- Name: tender_document_match_details tender_document_match_details_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_document_match_details
    ADD CONSTRAINT tender_document_match_details_pkey PRIMARY KEY (id);


--
-- Name: tender_document_matches tender_document_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_document_matches
    ADD CONSTRAINT tender_document_matches_pkey PRIMARY KEY (id);


--
-- Name: tender_plan_2020 tender_plan_2020_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020
    ADD CONSTRAINT tender_plan_2020_pkey PRIMARY KEY (id);


--
-- Name: tender_plan_2020_position tender_plan_2020_position_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_position
    ADD CONSTRAINT tender_plan_2020_position_pkey PRIMARY KEY (id);


--
-- Name: tender_plan_2020_progress tender_plan_2020_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_progress
    ADD CONSTRAINT tender_plan_2020_progress_pkey PRIMARY KEY (id);


--
-- Name: tender_statuses tender_statuses_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_statuses
    ADD CONSTRAINT tender_statuses_name_key UNIQUE (name);


--
-- Name: tender_statuses tender_statuses_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_statuses
    ADD CONSTRAINT tender_statuses_pkey PRIMARY KEY (id);


--
-- Name: tenders tenders_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenders
    ADD CONSTRAINT tenders_code_key UNIQUE (code);


--
-- Name: tenders tenders_external_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenders
    ADD CONSTRAINT tenders_external_id_key UNIQUE (external_id);


--
-- Name: tenders tenders_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenders
    ADD CONSTRAINT tenders_pkey PRIMARY KEY (id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_pkey PRIMARY KEY (id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_token_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_token_id_key UNIQUE (token_id);


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq UNIQUE (jti);


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_pkey PRIMARY KEY (id);


--
-- Name: trading_platform trading_platform_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trading_platform
    ADD CONSTRAINT trading_platform_pkey PRIMARY KEY (id);


--
-- Name: collection_codes_okpd unique_main_code; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.collection_codes_okpd
    ADD CONSTRAINT unique_main_code UNIQUE (main_code);


--
-- Name: collection_codes_okpd unique_sub_code; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.collection_codes_okpd
    ADD CONSTRAINT unique_sub_code UNIQUE (sub_code);


--
-- Name: tender_document_matches unique_tender_file_match; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_document_matches
    ADD CONSTRAINT unique_tender_file_match UNIQUE (tender_id, registry_type, file_name);


--
-- Name: okpd_categories unique_user_category_name; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_categories
    ADD CONSTRAINT unique_user_category_name UNIQUE (user_id, name);


--
-- Name: okpd_from_users unique_user_okpd_code; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_from_users
    ADD CONSTRAINT unique_user_okpd_code UNIQUE (user_id, okpd_code);


--
-- Name: tender_plan_2020 uq_tender_plan_2020; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020
    ADD CONSTRAINT uq_tender_plan_2020 UNIQUE (plan_number, version_number);


--
-- Name: tender_plan_2020_position uq_tp2020_position; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_position
    ADD CONSTRAINT uq_tp2020_position UNIQUE (plan_id, position_number);


--
-- Name: tender_plan_2020_progress uq_tp2020_progress; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_progress
    ADD CONSTRAINT uq_tp2020_progress UNIQUE (source_date, region_code);


--
-- Name: user_achievements user_achievements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_achievements
    ADD CONSTRAINT user_achievements_pkey PRIMARY KEY (id);


--
-- Name: user_achievements user_achievements_user_id_achievement_id_f7b407a9_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_achievements
    ADD CONSTRAINT user_achievements_user_id_achievement_id_f7b407a9_uniq UNIQUE (user_id, achievement_id);


--
-- Name: user_challenges user_challenges_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_challenges
    ADD CONSTRAINT user_challenges_pkey PRIMARY KEY (id);


--
-- Name: user_challenges user_challenges_user_id_challenge_id_684cb9ad_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_challenges
    ADD CONSTRAINT user_challenges_user_id_challenge_id_684cb9ad_uniq UNIQUE (user_id, challenge_id);


--
-- Name: user_credentials user_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_credentials
    ADD CONSTRAINT user_credentials_pkey PRIMARY KEY (id);


--
-- Name: user_learning_progress user_learning_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_learning_progress
    ADD CONSTRAINT user_learning_progress_pkey PRIMARY KEY (id);


--
-- Name: user_learning_progress user_learning_progress_user_id_material_id_8923a047_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_learning_progress
    ADD CONSTRAINT user_learning_progress_user_id_material_id_8923a047_uniq UNIQUE (user_id, material_id);


--
-- Name: user_locations user_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_locations
    ADD CONSTRAINT user_locations_pkey PRIMARY KEY (id);


--
-- Name: user_search_settings user_search_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_search_settings
    ADD CONSTRAINT user_search_settings_pkey PRIMARY KEY (user_id);


--
-- Name: users_blogpost users_blogpost_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_blogpost
    ADD CONSTRAINT users_blogpost_pkey PRIMARY KEY (id);


--
-- Name: users_blogpost users_blogpost_slug_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_blogpost
    ADD CONSTRAINT users_blogpost_slug_key UNIQUE (slug);


--
-- Name: users users_email_0ea73cca_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_0ea73cca_uniq UNIQUE (email);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users_groups users_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_pkey PRIMARY KEY (id);


--
-- Name: users_groups users_groups_user_id_group_id_fc7788e8_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_user_id_group_id_fc7788e8_uniq UNIQUE (user_id, group_id);


--
-- Name: users users_phone_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_phone_key UNIQUE (phone);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_telegram_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_telegram_user_id_key UNIQUE (telegram_user_id);


--
-- Name: users_user_permissions users_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: users_user_permissions users_user_permissions_user_id_permission_id_3b86cbdf_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissions_user_id_permission_id_3b86cbdf_uniq UNIQUE (user_id, permission_id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: webinar_registrations webinar_registrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.webinar_registrations
    ADD CONSTRAINT webinar_registrations_pkey PRIMARY KEY (id);


--
-- Name: webinar_registrations webinar_registrations_user_id_webinar_id_805cea7a_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.webinar_registrations
    ADD CONSTRAINT webinar_registrations_user_id_webinar_id_805cea7a_uniq UNIQUE (user_id, webinar_id);


--
-- Name: webinars webinars_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.webinars
    ADD CONSTRAINT webinars_pkey PRIMARY KEY (id);


--
-- Name: webinars webinars_slug_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.webinars
    ADD CONSTRAINT webinars_slug_key UNIQUE (slug);


--
-- Name: xp_transactions xp_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.xp_transactions
    ADD CONSTRAINT xp_transactions_pkey PRIMARY KEY (id);


--
-- Name: achievement_code_f4de4d_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX achievement_code_f4de4d_idx ON public.achievements USING btree (code);


--
-- Name: achievement_conditi_d3d918_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX achievement_conditi_d3d918_idx ON public.achievements USING btree (condition_type);


--
-- Name: achievements_code_84ae0e83_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX achievements_code_84ae0e83_like ON public.achievements USING btree (code varchar_pattern_ops);


--
-- Name: achievements_condition_type_0312e4f5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX achievements_condition_type_0312e4f5 ON public.achievements USING btree (condition_type);


--
-- Name: achievements_condition_type_0312e4f5_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX achievements_condition_type_0312e4f5_like ON public.achievements USING btree (condition_type varchar_pattern_ops);


--
-- Name: ai_analysis_analysi_5e6918_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_analysi_5e6918_idx ON public.ai_analysis_logs USING btree (analysis_type, created_at);


--
-- Name: ai_analysis_is_flag_5246b7_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_is_flag_5246b7_idx ON public.ai_analysis_logs USING btree (is_flagged);


--
-- Name: ai_analysis_logs_analysis_type_0799c910; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_analysis_type_0799c910 ON public.ai_analysis_logs USING btree (analysis_type);


--
-- Name: ai_analysis_logs_analysis_type_0799c910_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_analysis_type_0799c910_like ON public.ai_analysis_logs USING btree (analysis_type varchar_pattern_ops);


--
-- Name: ai_analysis_logs_created_at_435d07d0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_created_at_435d07d0 ON public.ai_analysis_logs USING btree (created_at);


--
-- Name: ai_analysis_logs_is_flagged_16386de8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_is_flagged_16386de8 ON public.ai_analysis_logs USING btree (is_flagged);


--
-- Name: ai_analysis_logs_tender_id_32160b03; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_tender_id_32160b03 ON public.ai_analysis_logs USING btree (tender_id);


--
-- Name: ai_analysis_logs_user_id_80d0739c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_user_id_80d0739c ON public.ai_analysis_logs USING btree (user_id);


--
-- Name: ai_analysis_logs_validation_status_7d861b4f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_validation_status_7d861b4f ON public.ai_analysis_logs USING btree (validation_status);


--
-- Name: ai_analysis_logs_validation_status_7d861b4f_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_logs_validation_status_7d861b4f_like ON public.ai_analysis_logs USING btree (validation_status varchar_pattern_ops);


--
-- Name: ai_analysis_tender__d674e9_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_tender__d674e9_idx ON public.ai_analysis_logs USING btree (tender_id, created_at);


--
-- Name: ai_analysis_user_id_6fec4c_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_user_id_6fec4c_idx ON public.ai_analysis_logs USING btree (user_id, created_at);


--
-- Name: ai_analysis_validat_c17263_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_analysis_validat_c17263_idx ON public.ai_analysis_logs USING btree (validation_status, created_at);


--
-- Name: ai_validation_reports_created_by_id_abbd7aba; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ai_validation_reports_created_by_id_abbd7aba ON public.ai_validation_reports USING btree (created_by_id);


--
-- Name: analytics_s_snapsho_25148f_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX analytics_s_snapsho_25148f_idx ON public.analytics_snapshots USING btree (snapshot_type, created_at);


--
-- Name: analytics_s_user_id_e5597c_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX analytics_s_user_id_e5597c_idx ON public.analytics_snapshots USING btree (user_id, snapshot_type, created_at);


--
-- Name: analytics_snapshots_created_at_70a8b0b1; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX analytics_snapshots_created_at_70a8b0b1 ON public.analytics_snapshots USING btree (created_at);


--
-- Name: analytics_snapshots_snapshot_type_e93aa061; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX analytics_snapshots_snapshot_type_e93aa061 ON public.analytics_snapshots USING btree (snapshot_type);


--
-- Name: analytics_snapshots_snapshot_type_e93aa061_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX analytics_snapshots_snapshot_type_e93aa061_like ON public.analytics_snapshots USING btree (snapshot_type varchar_pattern_ops);


--
-- Name: analytics_snapshots_user_id_f77c35cc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX analytics_snapshots_user_id_f77c35cc ON public.analytics_snapshots USING btree (user_id);


--
-- Name: application_categor_b9f2b4_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_categor_b9f2b4_idx ON public.application_templates USING btree (category);


--
-- Name: application_forms_status_d6dfd4c4; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_forms_status_d6dfd4c4 ON public.application_forms USING btree (status);


--
-- Name: application_forms_status_d6dfd4c4_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_forms_status_d6dfd4c4_like ON public.application_forms USING btree (status varchar_pattern_ops);


--
-- Name: application_forms_template_id_cfdb4430; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_forms_template_id_cfdb4430 ON public.application_forms USING btree (template_id);


--
-- Name: application_forms_tender_id_0b1380fa; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_forms_tender_id_0b1380fa ON public.application_forms USING btree (tender_id);


--
-- Name: application_forms_user_id_6785da04; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_forms_user_id_6785da04 ON public.application_forms USING btree (user_id);


--
-- Name: application_platfor_2d2717_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_platfor_2d2717_idx ON public.application_templates USING btree (platform);


--
-- Name: application_status_2b5117_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_status_2b5117_idx ON public.application_forms USING btree (status, created_at);


--
-- Name: application_templates_user_id_21910be7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_templates_user_id_21910be7 ON public.application_templates USING btree (user_id);


--
-- Name: application_tender__4a88ec_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_tender__4a88ec_idx ON public.application_forms USING btree (tender_id, status);


--
-- Name: application_user_id_327d1e_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_user_id_327d1e_idx ON public.application_templates USING btree (user_id, is_active);


--
-- Name: application_user_id_b355ff_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX application_user_id_b355ff_idx ON public.application_forms USING btree (user_id, status);


--
-- Name: audit_logs_action_327a0be3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_action_327a0be3 ON public.audit_logs USING btree (action);


--
-- Name: audit_logs_action_327a0be3_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_action_327a0be3_like ON public.audit_logs USING btree (action varchar_pattern_ops);


--
-- Name: audit_logs_action_391715_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_action_391715_idx ON public.audit_logs USING btree (action, created_at);


--
-- Name: audit_logs_created_262184_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_created_262184_idx ON public.audit_logs USING btree (created_at);


--
-- Name: audit_logs_created_at_939a9b33; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_created_at_939a9b33 ON public.audit_logs USING btree (created_at);


--
-- Name: audit_logs_ip_addr_b969fa_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_ip_addr_b969fa_idx ON public.audit_logs USING btree (ip_address, created_at);


--
-- Name: audit_logs_resourc_0fa0df_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_resourc_0fa0df_idx ON public.audit_logs USING btree (resource_type_id, resource_id);


--
-- Name: audit_logs_resource_type_id_80437372; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_resource_type_id_80437372 ON public.audit_logs USING btree (resource_type_id);


--
-- Name: audit_logs_user_id_752b0e2b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_user_id_752b0e2b ON public.audit_logs USING btree (user_id);


--
-- Name: audit_logs_user_id_fbfd51_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX audit_logs_user_id_fbfd51_idx ON public.audit_logs USING btree (user_id, created_at);


--
-- Name: calibration_metrics_calibration_weights_id_7ff625a8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX calibration_metrics_calibration_weights_id_7ff625a8 ON public.calibration_metrics USING btree (calibration_weights_id);


--
-- Name: calibration_weights_is_active_2ebf3483; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX calibration_weights_is_active_2ebf3483 ON public.calibration_weights USING btree (is_active);


--
-- Name: challenges_action__34d046_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_action__34d046_idx ON public.challenges USING btree (action_type);


--
-- Name: challenges_action_type_d5ee9343; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_action_type_d5ee9343 ON public.challenges USING btree (action_type);


--
-- Name: challenges_action_type_d5ee9343_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_action_type_d5ee9343_like ON public.challenges USING btree (action_type varchar_pattern_ops);


--
-- Name: challenges_challen_d8795b_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_challen_d8795b_idx ON public.challenges USING btree (challenge_type, is_active);


--
-- Name: challenges_challenge_type_859680ff; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_challenge_type_859680ff ON public.challenges USING btree (challenge_type);


--
-- Name: challenges_challenge_type_859680ff_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_challenge_type_859680ff_like ON public.challenges USING btree (challenge_type varchar_pattern_ops);


--
-- Name: challenges_is_active_f082ef04; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_is_active_f082ef04 ON public.challenges USING btree (is_active);


--
-- Name: challenges_is_feat_d87124_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_is_feat_d87124_idx ON public.challenges USING btree (is_featured, priority);


--
-- Name: challenges_is_featured_2dce6cee; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_is_featured_2dce6cee ON public.challenges USING btree (is_featured);


--
-- Name: challenges_priority_51b55f1d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_priority_51b55f1d ON public.challenges USING btree (priority);


--
-- Name: challenges_start_d_5caac7_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX challenges_start_d_5caac7_idx ON public.challenges USING btree (start_date, end_date);


--
-- Name: checklist_i_partici_cea2a5_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX checklist_i_partici_cea2a5_idx ON public.checklist_items USING btree (participation_id, is_completed);


--
-- Name: checklist_i_partici_f7fae1_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX checklist_i_partici_f7fae1_idx ON public.checklist_items USING btree (participation_id, stage);


--
-- Name: checklist_i_stage_faaf45_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX checklist_i_stage_faaf45_idx ON public.checklist_items USING btree (stage, "order");


--
-- Name: checklist_items_completed_by_id_36fdd30d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX checklist_items_completed_by_id_36fdd30d ON public.checklist_items USING btree (completed_by_id);


--
-- Name: checklist_items_participation_id_afb72141; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX checklist_items_participation_id_afb72141 ON public.checklist_items USING btree (participation_id);


--
-- Name: checklist_items_related_document_id_f5a3377e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX checklist_items_related_document_id_f5a3377e ON public.checklist_items USING btree (related_document_id);


--
-- Name: competitors_collusi_ee0730_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_collusi_ee0730_idx ON public.competitors USING btree (collusion_score);


--
-- Name: competitors_identif_496695_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_identif_496695_idx ON public.competitors USING btree (identifier);


--
-- Name: competitors_identifier_d95bcec9_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_identifier_d95bcec9_like ON public.competitors USING btree (identifier varchar_pattern_ops);


--
-- Name: competitors_inn_7b7139_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_inn_7b7139_idx ON public.competitors USING btree (inn);


--
-- Name: competitors_inn_add9addc; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_inn_add9addc ON public.competitors USING btree (inn);


--
-- Name: competitors_inn_add9addc_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_inn_add9addc_like ON public.competitors USING btree (inn varchar_pattern_ops);


--
-- Name: competitors_name_66224213; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_name_66224213 ON public.competitors USING btree (name);


--
-- Name: competitors_name_66224213_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_name_66224213_like ON public.competitors USING btree (name varchar_pattern_ops);


--
-- Name: competitors_region_4baa8ec1; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_region_4baa8ec1 ON public.competitors USING btree (region);


--
-- Name: competitors_region_4baa8ec1_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_region_4baa8ec1_like ON public.competitors USING btree (region varchar_pattern_ops);


--
-- Name: competitors_region_c7d4fa_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_region_c7d4fa_idx ON public.competitors USING btree (region);


--
-- Name: competitors_win_rat_3724d2_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX competitors_win_rat_3724d2_idx ON public.competitors USING btree (win_rate);


--
-- Name: consultatio_schedul_b28f00_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultatio_schedul_b28f00_idx ON public.consultations USING btree (scheduled_at);


--
-- Name: consultatio_status_d0eef3_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultatio_status_d0eef3_idx ON public.consultations USING btree (status, scheduled_at);


--
-- Name: consultatio_user_id_1c0979_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultatio_user_id_1c0979_idx ON public.consultations USING btree (user_id, status);


--
-- Name: consultations_created_at_0cb071f3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultations_created_at_0cb071f3 ON public.consultations USING btree (created_at);


--
-- Name: consultations_status_970e173b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultations_status_970e173b ON public.consultations USING btree (status);


--
-- Name: consultations_status_970e173b_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultations_status_970e173b_like ON public.consultations USING btree (status varchar_pattern_ops);


--
-- Name: consultations_user_id_69394594; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX consultations_user_id_69394594 ON public.consultations USING btree (user_id);


--
-- Name: customers_inn_52acde_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_inn_52acde_idx ON public.customers USING btree (inn);


--
-- Name: customers_inn_6b5b8071_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_inn_6b5b8071_like ON public.customers USING btree (inn varchar_pattern_ops);


--
-- Name: customers_name_dd11b9a1; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_name_dd11b9a1 ON public.customers USING btree (name);


--
-- Name: customers_name_dd11b9a1_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_name_dd11b9a1_like ON public.customers USING btree (name varchar_pattern_ops);


--
-- Name: customers_region_548ea5_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_region_548ea5_idx ON public.customers USING btree (region);


--
-- Name: customers_region_5fc75a8e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_region_5fc75a8e ON public.customers USING btree (region);


--
-- Name: customers_region_5fc75a8e_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_region_5fc75a8e_like ON public.customers USING btree (region varchar_pattern_ops);


--
-- Name: customers_reliabi_12f493_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_reliabi_12f493_idx ON public.customers USING btree (reliability_rating);


--
-- Name: customers_reliability_rating_fbd91bec; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_reliability_rating_fbd91bec ON public.customers USING btree (reliability_rating);


--
-- Name: customers_reliability_rating_fbd91bec_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_reliability_rating_fbd91bec_like ON public.customers USING btree (reliability_rating varchar_pattern_ops);


--
-- Name: customers_termina_9e27ac_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX customers_termina_9e27ac_idx ON public.customers USING btree (termination_rate);


--
-- Name: daily_quest_quest_t_f0de78_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quest_quest_t_f0de78_idx ON public.daily_quests USING btree (quest_type);


--
-- Name: daily_quest_user_id_0c1b47_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quest_user_id_0c1b47_idx ON public.daily_quests USING btree (user_id, completed_at);


--
-- Name: daily_quest_user_id_2c6db2_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quest_user_id_2c6db2_idx ON public.daily_quests USING btree (user_id, created_at);


--
-- Name: daily_quests_completed_at_87533e5c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quests_completed_at_87533e5c ON public.daily_quests USING btree (completed_at);


--
-- Name: daily_quests_created_at_13ffe27c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quests_created_at_13ffe27c ON public.daily_quests USING btree (created_at);


--
-- Name: daily_quests_quest_type_4f7e8c48; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quests_quest_type_4f7e8c48 ON public.daily_quests USING btree (quest_type);


--
-- Name: daily_quests_quest_type_4f7e8c48_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quests_quest_type_4f7e8c48_like ON public.daily_quests USING btree (quest_type varchar_pattern_ops);


--
-- Name: daily_quests_user_id_0e20c860; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX daily_quests_user_id_0e20c860 ON public.daily_quests USING btree (user_id);


--
-- Name: deadline_ev_deadlin_fc263f_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_ev_deadlin_fc263f_idx ON public.deadline_events USING btree (deadline_at, status);


--
-- Name: deadline_ev_locatio_490bfe_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_ev_locatio_490bfe_idx ON public.deadline_events USING btree (location_lat, location_lon);


--
-- Name: deadline_ev_priorit_286318_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_ev_priorit_286318_idx ON public.deadline_events USING btree (priority);


--
-- Name: deadline_ev_reminde_81e9cd_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_ev_reminde_81e9cd_idx ON public.deadline_events USING btree (reminder_at);


--
-- Name: deadline_ev_user_id_af39f8_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_ev_user_id_af39f8_idx ON public.deadline_events USING btree (user_id, deadline_at);


--
-- Name: deadline_ev_user_id_c59c23_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_ev_user_id_c59c23_idx ON public.deadline_events USING btree (user_id, status);


--
-- Name: deadline_events_amocrm_task_id_74181fa7; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_amocrm_task_id_74181fa7 ON public.deadline_events USING btree (amocrm_task_id);


--
-- Name: deadline_events_amocrm_task_id_74181fa7_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_amocrm_task_id_74181fa7_like ON public.deadline_events USING btree (amocrm_task_id varchar_pattern_ops);


--
-- Name: deadline_events_bitrix24_task_id_180ca30c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_bitrix24_task_id_180ca30c ON public.deadline_events USING btree (bitrix24_task_id);


--
-- Name: deadline_events_bitrix24_task_id_180ca30c_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_bitrix24_task_id_180ca30c_like ON public.deadline_events USING btree (bitrix24_task_id varchar_pattern_ops);


--
-- Name: deadline_events_deadline_at_f4409daa; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_deadline_at_f4409daa ON public.deadline_events USING btree (deadline_at);


--
-- Name: deadline_events_event_type_29b94ceb; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_event_type_29b94ceb ON public.deadline_events USING btree (event_type);


--
-- Name: deadline_events_event_type_29b94ceb_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_event_type_29b94ceb_like ON public.deadline_events USING btree (event_type varchar_pattern_ops);


--
-- Name: deadline_events_participation_id_b51c9473; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_participation_id_b51c9473 ON public.deadline_events USING btree (participation_id);


--
-- Name: deadline_events_priority_b6eb0b6e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_priority_b6eb0b6e ON public.deadline_events USING btree (priority);


--
-- Name: deadline_events_priority_b6eb0b6e_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_priority_b6eb0b6e_like ON public.deadline_events USING btree (priority varchar_pattern_ops);


--
-- Name: deadline_events_reminder_at_07db7e6f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_reminder_at_07db7e6f ON public.deadline_events USING btree (reminder_at);


--
-- Name: deadline_events_status_6854ab48; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_status_6854ab48 ON public.deadline_events USING btree (status);


--
-- Name: deadline_events_status_6854ab48_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_status_6854ab48_like ON public.deadline_events USING btree (status varchar_pattern_ops);


--
-- Name: deadline_events_tender_id_765423f0; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_tender_id_765423f0 ON public.deadline_events USING btree (tender_id);


--
-- Name: deadline_events_user_id_da44df3e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX deadline_events_user_id_da44df3e ON public.deadline_events USING btree (user_id);


--
-- Name: idx_615_nspd_match_cad; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_615_nspd_match_cad ON public.reestr_contract_615_pp_nspd_match USING btree (cadastral_object_id);


--
-- Name: idx_615_nspd_match_score; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_615_nspd_match_score ON public.reestr_contract_615_pp_nspd_match USING btree (match_score DESC);


--
-- Name: idx_615_nspd_match_uk; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_615_nspd_match_uk ON public.reestr_contract_615_pp_nspd_match USING btree (management_company_id);


--
-- Name: idx_collection_codes_okpd; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_collection_codes_okpd ON public.collection_codes_okpd USING btree (main_code, sub_code);


--
-- Name: idx_contact_link_contact_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_contact_link_contact_id ON public.contact_link USING btree (contact_id);


--
-- Name: idx_contact_link_contractor_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_contact_link_contractor_id ON public.contact_link USING btree (contractor_id);


--
-- Name: idx_contact_link_customer_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_contact_link_customer_id ON public.contact_link USING btree (customer_id);


--
-- Name: idx_contact_link_deal_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_contact_link_deal_id ON public.contact_link USING btree (deal_id);


--
-- Name: idx_deal_chat_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deal_chat_created_at ON public.deal_chat USING btree (created_at DESC);


--
-- Name: idx_deal_chat_deal_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deal_chat_deal_id ON public.deal_chat USING btree (deal_id);


--
-- Name: idx_deal_chat_sender_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deal_chat_sender_id ON public.deal_chat USING btree (sender_id) WHERE (sender_id IS NOT NULL);


--
-- Name: idx_deal_item_deal_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deal_item_deal_id ON public.deal_item USING btree (deal_id);


--
-- Name: idx_deal_item_deal_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deal_item_deal_type ON public.deal_item USING btree (deal_id, item_type);


--
-- Name: idx_deal_item_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deal_item_type ON public.deal_item USING btree (item_type);


--
-- Name: idx_deals_pipeline_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deals_pipeline_type ON public.sales_deals USING btree (pipeline_type);


--
-- Name: idx_deals_stage_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deals_stage_id ON public.sales_deals USING btree (stage_id);


--
-- Name: idx_deals_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_deals_user_id ON public.sales_deals USING btree (user_id);


--
-- Name: idx_dpq_contract_reg_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_dpq_contract_reg_number ON public.document_processing_queue USING btree (contract_reg_number);


--
-- Name: idx_etws_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_etws_status ON public.expertise_tender_window_score USING btree (status);


--
-- Name: idx_etws_window; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_etws_window ON public.expertise_tender_window_score USING btree (window_start, window_end);


--
-- Name: idx_file_names_xml_processed_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_file_names_xml_processed_at ON public.file_names_xml USING btree (processed_at DESC);


--
-- Name: idx_links_arch_223_cid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_arch_223_cid ON public.links_documentation_223_fz_archive USING btree (contract_id);


--
-- Name: idx_links_arch_223_cn; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_arch_223_cn ON public.links_documentation_223_fz_archive USING btree (contract_number);


--
-- Name: idx_links_arch_44_cid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_arch_44_cid ON public.links_documentation_44_fz_archive USING btree (contract_id);


--
-- Name: idx_links_arch_44_cn; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_arch_44_cn ON public.links_documentation_44_fz_archive USING btree (contract_number);


--
-- Name: idx_links_documentation_223_fz_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_documentation_223_fz_contract_number ON public.links_documentation_223_fz USING btree (contract_number);


--
-- Name: idx_links_documentation_44_fz_contract_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_documentation_44_fz_contract_id ON public.links_documentation_44_fz USING btree (contract_id);


--
-- Name: idx_links_documentation_44_fz_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_documentation_44_fz_contract_number ON public.links_documentation_44_fz USING btree (contract_number);


--
-- Name: idx_links_documentation_615_pp_contract_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_documentation_615_pp_contract_id ON public.links_documentation_615_pp USING btree (contract_id);


--
-- Name: idx_links_documentation_615_pp_cw_contract_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_documentation_615_pp_cw_contract_id ON public.links_documentation_615_pp_commission_work USING btree (contract_id);


--
-- Name: idx_match_details_match_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_match_details_match_id ON public.tender_document_match_details USING btree (match_id);


--
-- Name: idx_object_type_classifications_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_type_classifications_contract_number ON public.crm_object_type_classifications USING btree (contract_number);


--
-- Name: idx_object_type_classifications_object_type_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_type_classifications_object_type_code ON public.crm_object_type_classifications USING btree (object_type_code);


--
-- Name: idx_object_type_classifications_object_uid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_type_classifications_object_uid ON public.crm_object_type_classifications USING btree (object_uid);


--
-- Name: idx_object_type_classifications_primary_class_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_type_classifications_primary_class_code ON public.crm_object_type_classifications USING btree (primary_class_code);


--
-- Name: idx_object_type_classifications_registry_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_type_classifications_registry_type ON public.crm_object_type_classifications USING btree (registry_type);


--
-- Name: idx_object_type_classifications_tender_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_type_classifications_tender_id ON public.crm_object_type_classifications USING btree (tender_id);


--
-- Name: idx_okpd_categories_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_okpd_categories_user_id ON public.okpd_categories USING btree (user_id);


--
-- Name: idx_okpd_from_users_category_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_okpd_from_users_category_id ON public.okpd_from_users USING btree (category_id);


--
-- Name: idx_okpd_startdate; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_okpd_startdate ON public.reestr_contract_44_fz USING btree (okpd_id, start_date DESC);


--
-- Name: idx_okpd_startdate_223fz; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_okpd_startdate_223fz ON public.reestr_contract_223_fz USING btree (okpd_id, start_date DESC);


--
-- Name: idx_okpd_sub_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_okpd_sub_code ON public.collection_codes_okpd USING btree (sub_code) WHERE (sub_code IS NOT NULL);


--
-- Name: idx_processed_files_machine; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_files_machine ON public.processed_files USING btree (machine_id);


--
-- Name: idx_processed_files_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_files_status ON public.processed_files USING btree (processing_status);


--
-- Name: idx_processed_files_tender; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_files_tender ON public.processed_files USING btree (tender_id, registry_type);


--
-- Name: idx_processed_tenders_folder; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_tenders_folder ON public.processed_tenders USING btree (folder_name);


--
-- Name: idx_processed_tenders_machine; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_tenders_machine ON public.processed_tenders USING btree (machine_id);


--
-- Name: idx_processed_tenders_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_tenders_status ON public.processed_tenders USING btree (processing_status);


--
-- Name: idx_processed_tenders_tender; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_tenders_tender ON public.processed_tenders USING btree (tender_id, registry_type);


--
-- Name: idx_processed_tenders_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_processed_tenders_user ON public.processed_tenders USING btree (user_id);


--
-- Name: idx_queue_contract; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_queue_contract ON public.document_processing_queue USING btree (contract_reg_number);


--
-- Name: idx_queue_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_queue_status ON public.document_processing_queue USING btree (status);


--
-- Name: idx_reestr_223_awarded_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_223_awarded_contract_number ON public.reestr_contract_223_fz_awarded USING btree (contract_number) WHERE (contract_number IS NOT NULL);


--
-- Name: idx_reestr_223_fz_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_223_fz_contract_number ON public.reestr_contract_223_fz USING btree (contract_number) WHERE (contract_number IS NOT NULL);


--
-- Name: idx_reestr_44_awarded_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_44_awarded_contract_number ON public.reestr_contract_44_fz_awarded USING btree (contract_number) WHERE (contract_number IS NOT NULL);


--
-- Name: idx_reestr_44_awarded_region; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_44_awarded_region ON public.reestr_contract_44_fz_awarded USING btree (region_id);


--
-- Name: idx_reestr_44_fz_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_44_fz_contract_number ON public.reestr_contract_44_fz USING btree (contract_number) WHERE (contract_number IS NOT NULL);


--
-- Name: idx_reestr_615_pp_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_615_pp_contract_number ON public.reestr_contract_615_pp USING btree (contract_number) WHERE (contract_number IS NOT NULL);


--
-- Name: idx_reestr_contract_223_fz_awarded_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_awarded_contract_number ON public.reestr_contract_223_fz_awarded USING btree (contract_number);


--
-- Name: idx_reestr_contract_223_fz_awarded_region_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_awarded_region_id ON public.reestr_contract_223_fz_awarded USING btree (region_id);


--
-- Name: idx_reestr_contract_223_fz_commission_work_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_commission_work_contract_number ON public.reestr_contract_223_fz_commission_work USING btree (contract_number);


--
-- Name: idx_reestr_contract_223_fz_completed_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_completed_contract_number ON public.reestr_contract_223_fz_completed USING btree (contract_number);


--
-- Name: idx_reestr_contract_223_fz_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_contract_number ON public.reestr_contract_223_fz USING btree (contract_number);


--
-- Name: idx_reestr_contract_223_fz_region_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_region_id ON public.reestr_contract_223_fz USING btree (region_id);


--
-- Name: idx_reestr_contract_223_fz_status_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_status_id ON public.reestr_contract_223_fz USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: idx_reestr_contract_223_fz_unclear_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_223_fz_unclear_contract_number ON public.reestr_contract_223_fz_unclear USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_awarded_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_awarded_contract_number ON public.reestr_contract_44_fz_awarded USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_awarded_region_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_awarded_region_id ON public.reestr_contract_44_fz_awarded USING btree (region_id);


--
-- Name: idx_reestr_contract_44_fz_bad_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_bad_contract_number ON public.reestr_contract_44_fz_bad USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_commission_work_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_commission_work_contract_number ON public.reestr_contract_44_fz_commission_work USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_completed_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_completed_contract_number ON public.reestr_contract_44_fz_completed USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_contract_number ON public.reestr_contract_44_fz USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_region_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_region_id ON public.reestr_contract_44_fz USING btree (region_id);


--
-- Name: idx_reestr_contract_44_fz_status_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_status_id ON public.reestr_contract_44_fz USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: idx_reestr_contract_44_fz_unclear_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_unclear_contract_number ON public.reestr_contract_44_fz_unclear USING btree (contract_number);


--
-- Name: idx_reestr_contract_44_fz_unknown_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_44_fz_unknown_contract_number ON public.reestr_contract_44_fz_unknown USING btree (contract_number);


--
-- Name: idx_reestr_contract_615_pp_commission_work_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_commission_work_contract_number ON public.reestr_contract_615_pp_commission_work USING btree (contract_number);


--
-- Name: idx_reestr_contract_615_pp_contract_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_contract_number ON public.reestr_contract_615_pp USING btree (contract_number);


--
-- Name: idx_reestr_contract_615_pp_cw_okpd_startdate; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_cw_okpd_startdate ON public.reestr_contract_615_pp_commission_work USING btree (okpd_id, start_date DESC);


--
-- Name: idx_reestr_contract_615_pp_cw_status_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_cw_status_id ON public.reestr_contract_615_pp_commission_work USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: idx_reestr_contract_615_pp_okpd_startdate; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_okpd_startdate ON public.reestr_contract_615_pp USING btree (okpd_id, start_date DESC);


--
-- Name: idx_reestr_contract_615_pp_region_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_region_id ON public.reestr_contract_615_pp USING btree (region_id);


--
-- Name: idx_reestr_contract_615_pp_status_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_reestr_contract_615_pp_status_id ON public.reestr_contract_615_pp USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: idx_server_metrics_recorded; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_server_metrics_recorded ON public.server_metrics USING btree (server_id, recorded_at DESC);


--
-- Name: idx_tdm_interesting_lookup; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tdm_interesting_lookup ON public.tender_document_matches USING btree (is_interesting, registry_type) WHERE (is_interesting = true);


--
-- Name: idx_tdm_interesting_registry_tender; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tdm_interesting_registry_tender ON public.tender_document_matches USING btree (registry_type, tender_id) WHERE (is_interesting = true);


--
-- Name: idx_tender_matches_error_reason; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tender_matches_error_reason ON public.tender_document_matches USING btree (error_reason) WHERE (error_reason IS NOT NULL);


--
-- Name: idx_tender_matches_has_error; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tender_matches_has_error ON public.tender_document_matches USING btree (has_error) WHERE (has_error = true);


--
-- Name: idx_tender_matches_is_interesting; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tender_matches_is_interesting ON public.tender_document_matches USING btree (is_interesting);


--
-- Name: idx_tender_matches_match_percentage; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tender_matches_match_percentage ON public.tender_document_matches USING btree (match_percentage);


--
-- Name: idx_tender_matches_processed_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tender_matches_processed_at ON public.tender_document_matches USING btree (processed_at);


--
-- Name: idx_tender_matches_registry_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tender_matches_registry_type ON public.tender_document_matches USING btree (registry_type);


--
-- Name: idx_tp2020_customer_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_customer_id ON public.tender_plan_2020 USING btree (customer_id);


--
-- Name: idx_tp2020_customer_inn; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_customer_inn ON public.tender_plan_2020 USING btree (customer_inn);


--
-- Name: idx_tp2020_plan_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_plan_number ON public.tender_plan_2020 USING btree (plan_number);


--
-- Name: idx_tp2020_plan_year; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_plan_year ON public.tender_plan_2020 USING btree (plan_year);


--
-- Name: idx_tp2020_pos_canceled; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_canceled ON public.tender_plan_2020_position USING btree (is_canceled);


--
-- Name: idx_tp2020_pos_contract_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_contract_id ON public.tender_plan_2020_position USING btree (contract_44_id);


--
-- Name: idx_tp2020_pos_ikz; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_ikz ON public.tender_plan_2020_position USING btree (ikz);


--
-- Name: idx_tp2020_pos_okpd2_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_okpd2_code ON public.tender_plan_2020_position USING btree (okpd2_code);


--
-- Name: idx_tp2020_pos_okpd2_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_okpd2_id ON public.tender_plan_2020_position USING btree (okpd2_id);


--
-- Name: idx_tp2020_pos_plan_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_plan_id ON public.tender_plan_2020_position USING btree (plan_id);


--
-- Name: idx_tp2020_pos_publish_year; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_pos_publish_year ON public.tender_plan_2020_position USING btree (publish_year);


--
-- Name: idx_tp2020_publish_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_publish_date ON public.tender_plan_2020 USING btree (publish_date);


--
-- Name: idx_tp2020_region_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tp2020_region_code ON public.tender_plan_2020 USING btree (region_code);


--
-- Name: idx_unique_contact; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_unique_contact ON public.customer USING btree (contact);


--
-- Name: idx_unique_contact_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_unique_contact_email ON public.customer USING btree (contact_email);


--
-- Name: idx_unique_contact_phone; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_unique_contact_phone ON public.customer USING btree (contact_phone);


--
-- Name: idx_user_search_settings_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_search_settings_user_id ON public.user_search_settings USING btree (user_id);


--
-- Name: integration_integra_db3052_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integration_integra_db3052_idx ON public.integrations USING btree (integration_type, is_active);


--
-- Name: integration_user_id_84cd70_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integration_user_id_84cd70_idx ON public.integrations USING btree (user_id, is_active);


--
-- Name: integration_user_id_a0bc83_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integration_user_id_a0bc83_idx ON public.integrations USING btree (user_id, integration_type);


--
-- Name: integrations_external_id_8cbc38e8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integrations_external_id_8cbc38e8 ON public.integrations USING btree (external_id);


--
-- Name: integrations_external_id_8cbc38e8_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integrations_external_id_8cbc38e8_like ON public.integrations USING btree (external_id varchar_pattern_ops);


--
-- Name: integrations_integration_type_af24329b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integrations_integration_type_af24329b ON public.integrations USING btree (integration_type);


--
-- Name: integrations_integration_type_af24329b_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integrations_integration_type_af24329b_like ON public.integrations USING btree (integration_type varchar_pattern_ops);


--
-- Name: integrations_is_active_25d93b7f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integrations_is_active_25d93b7f ON public.integrations USING btree (is_active);


--
-- Name: integrations_user_id_8162b4e4; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX integrations_user_id_8162b4e4 ON public.integrations USING btree (user_id);


--
-- Name: invoices_invoice_7778bc_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX invoices_invoice_7778bc_idx ON public.invoices USING btree (invoice_number);


--
-- Name: invoices_invoice_number_d71e3c2e_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX invoices_invoice_number_d71e3c2e_like ON public.invoices USING btree (invoice_number varchar_pattern_ops);


--
-- Name: invoices_payment_d3abef_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX invoices_payment_d3abef_idx ON public.invoices USING btree (payment_id);


--
-- Name: invoices_payment_id_d20b1255; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX invoices_payment_id_d20b1255 ON public.invoices USING btree (payment_id);


--
-- Name: ix_crm_docs_priority_hints_contour; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_docs_priority_hints_contour ON public.crm_docs_priority_hints USING btree (contour, ai_priority_score DESC, updated_at DESC);


--
-- Name: ix_crm_unified_links_uid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_unified_links_uid ON public.crm_unified_object_links USING btree (object_uid, created_at DESC);


--
-- Name: ix_crm_unified_signals_uid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_crm_unified_signals_uid ON public.crm_unified_signals USING btree (object_uid, created_at DESC);


--
-- Name: learning_ma_categor_6ea628_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_ma_categor_6ea628_idx ON public.learning_materials USING btree (category, is_published);


--
-- Name: learning_ma_difficu_03c9a3_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_ma_difficu_03c9a3_idx ON public.learning_materials USING btree (difficulty, is_published);


--
-- Name: learning_ma_is_feat_98c898_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_ma_is_feat_98c898_idx ON public.learning_materials USING btree (is_featured, priority);


--
-- Name: learning_ma_materia_df3cc2_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_ma_materia_df3cc2_idx ON public.learning_materials USING btree (material_type, is_published);


--
-- Name: learning_materials_category_e79c9fc2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_category_e79c9fc2 ON public.learning_materials USING btree (category);


--
-- Name: learning_materials_category_e79c9fc2_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_category_e79c9fc2_like ON public.learning_materials USING btree (category varchar_pattern_ops);


--
-- Name: learning_materials_difficulty_805165ea; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_difficulty_805165ea ON public.learning_materials USING btree (difficulty);


--
-- Name: learning_materials_difficulty_805165ea_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_difficulty_805165ea_like ON public.learning_materials USING btree (difficulty varchar_pattern_ops);


--
-- Name: learning_materials_is_featured_f4a8fe61; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_is_featured_f4a8fe61 ON public.learning_materials USING btree (is_featured);


--
-- Name: learning_materials_is_published_69e9b35c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_is_published_69e9b35c ON public.learning_materials USING btree (is_published);


--
-- Name: learning_materials_material_type_5946d4bf; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_material_type_5946d4bf ON public.learning_materials USING btree (material_type);


--
-- Name: learning_materials_material_type_5946d4bf_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_material_type_5946d4bf_like ON public.learning_materials USING btree (material_type varchar_pattern_ops);


--
-- Name: learning_materials_priority_2f34cfef; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_priority_2f34cfef ON public.learning_materials USING btree (priority);


--
-- Name: learning_materials_slug_73279a07_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX learning_materials_slug_73279a07_like ON public.learning_materials USING btree (slug varchar_pattern_ops);


--
-- Name: mfa_backup__code_ha_45daf5_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_backup__code_ha_45daf5_idx ON public.mfa_backup_codes USING btree (code_hash);


--
-- Name: mfa_backup__user_id_f9d223_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_backup__user_id_f9d223_idx ON public.mfa_backup_codes USING btree (user_id, is_used);


--
-- Name: mfa_backup_codes_code_hash_91afdaad; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_backup_codes_code_hash_91afdaad ON public.mfa_backup_codes USING btree (code_hash);


--
-- Name: mfa_backup_codes_code_hash_91afdaad_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_backup_codes_code_hash_91afdaad_like ON public.mfa_backup_codes USING btree (code_hash varchar_pattern_ops);


--
-- Name: mfa_backup_codes_is_used_cd452993; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_backup_codes_is_used_cd452993 ON public.mfa_backup_codes USING btree (is_used);


--
-- Name: mfa_backup_codes_user_id_f182b2cd; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_backup_codes_user_id_f182b2cd ON public.mfa_backup_codes USING btree (user_id);


--
-- Name: mfa_devices_device__b12961_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_devices_device__b12961_idx ON public.mfa_devices USING btree (device_type);


--
-- Name: mfa_devices_user_id_489d37_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_devices_user_id_489d37_idx ON public.mfa_devices USING btree (user_id, is_primary);


--
-- Name: mfa_devices_user_id_5a090826; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_devices_user_id_5a090826 ON public.mfa_devices USING btree (user_id);


--
-- Name: mfa_devices_user_id_aaf6f4_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX mfa_devices_user_id_aaf6f4_idx ON public.mfa_devices USING btree (user_id, is_active);


--
-- Name: notificatio_notific_19df93_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notificatio_notific_19df93_idx ON public.notifications USING btree (notification_type);


--
-- Name: notificatio_user_id_7336fd_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notificatio_user_id_7336fd_idx ON public.notifications USING btree (user_id, created_at);


--
-- Name: notificatio_user_id_a4dd5c_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notificatio_user_id_a4dd5c_idx ON public.notifications USING btree (user_id, is_read);


--
-- Name: notifications_created_at_878ec15c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_created_at_878ec15c ON public.notifications USING btree (created_at);


--
-- Name: notifications_is_read_27cb7368; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_is_read_27cb7368 ON public.notifications USING btree (is_read);


--
-- Name: notifications_notification_type_6222bc26; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_notification_type_6222bc26 ON public.notifications USING btree (notification_type);


--
-- Name: notifications_notification_type_6222bc26_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_notification_type_6222bc26_like ON public.notifications USING btree (notification_type varchar_pattern_ops);


--
-- Name: notifications_related_participation_id_a0665b92; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_related_participation_id_a0665b92 ON public.notifications USING btree (related_participation_id);


--
-- Name: notifications_related_tender_id_e2382904; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_related_tender_id_e2382904 ON public.notifications USING btree (related_tender_id);


--
-- Name: notifications_user_id_468e288d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX notifications_user_id_468e288d ON public.notifications USING btree (user_id);


--
-- Name: onboarding__current_f44778_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX onboarding__current_f44778_idx ON public.onboarding_progress USING btree (current_step);


--
-- Name: onboarding__user_id_0183e8_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX onboarding__user_id_0183e8_idx ON public.onboarding_progress USING btree (user_id, is_completed);


--
-- Name: parser_logs_created_at_ed95b240; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_created_at_ed95b240 ON public.parser_logs USING btree (created_at);


--
-- Name: parser_logs_finished_at_8af8e499; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_finished_at_8af8e499 ON public.parser_logs USING btree (finished_at);


--
-- Name: parser_logs_platfor_04b566_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_platfor_04b566_idx ON public.parser_logs USING btree (platform, started_at);


--
-- Name: parser_logs_platform_b86326ce; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_platform_b86326ce ON public.parser_logs USING btree (platform);


--
-- Name: parser_logs_platform_b86326ce_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_platform_b86326ce_like ON public.parser_logs USING btree (platform varchar_pattern_ops);


--
-- Name: parser_logs_started_21a2a5_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_started_21a2a5_idx ON public.parser_logs USING btree (started_at);


--
-- Name: parser_logs_started_at_47fa70ad; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_started_at_47fa70ad ON public.parser_logs USING btree (started_at);


--
-- Name: parser_logs_status_8b7b5a_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_status_8b7b5a_idx ON public.parser_logs USING btree (status, started_at);


--
-- Name: parser_logs_status_ac399d04; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_status_ac399d04 ON public.parser_logs USING btree (status);


--
-- Name: parser_logs_status_ac399d04_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX parser_logs_status_ac399d04_like ON public.parser_logs USING btree (status varchar_pattern_ops);


--
-- Name: participati_changed_0ed3d1_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX participati_changed_0ed3d1_idx ON public.participation_status_history USING btree (changed_at);


--
-- Name: participati_partici_4d2f5e_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX participati_partici_4d2f5e_idx ON public.participation_status_history USING btree (participation_id, changed_at);


--
-- Name: participati_partici_c3730e_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX participati_partici_c3730e_idx ON public.participation_status_history USING btree (participation_id, new_status);


--
-- Name: participation_status_history_changed_at_0096130f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX participation_status_history_changed_at_0096130f ON public.participation_status_history USING btree (changed_at);


--
-- Name: participation_status_history_changed_by_id_2c30924f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX participation_status_history_changed_by_id_2c30924f ON public.participation_status_history USING btree (changed_by_id);


--
-- Name: participation_status_history_participation_id_4848fb65; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX participation_status_history_participation_id_4848fb65 ON public.participation_status_history USING btree (participation_id);


--
-- Name: payments_status_426d4f_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_status_426d4f_idx ON public.payments USING btree (status, created_at);


--
-- Name: payments_status_760e149d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_status_760e149d ON public.payments USING btree (status);


--
-- Name: payments_status_760e149d_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_status_760e149d_like ON public.payments USING btree (status varchar_pattern_ops);


--
-- Name: payments_subscri_500936_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_subscri_500936_idx ON public.payments USING btree (subscription_id, status);


--
-- Name: payments_subscription_id_956d9d05; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_subscription_id_956d9d05 ON public.payments USING btree (subscription_id);


--
-- Name: payments_yookass_ad8fbb_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_yookass_ad8fbb_idx ON public.payments USING btree (yookassa_payment_id);


--
-- Name: payments_yookassa_payment_id_125cfceb_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX payments_yookassa_payment_id_125cfceb_like ON public.payments USING btree (yookassa_payment_id varchar_pattern_ops);


--
-- Name: push_subscr_endpoin_48e896_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX push_subscr_endpoin_48e896_idx ON public.push_subscriptions USING btree (endpoint);


--
-- Name: push_subscr_user_id_41d090_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX push_subscr_user_id_41d090_idx ON public.push_subscriptions USING btree (user_id);


--
-- Name: push_subscriptions_user_id_7dd0cc78; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX push_subscriptions_user_id_7dd0cc78 ON public.push_subscriptions USING btree (user_id);


--
-- Name: reestr_contract_223_fz_awarded_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_awarded_okpd_id_start_date_idx ON public.reestr_contract_223_fz_awarded USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_223_fz_awarded_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_awarded_status_id_idx ON public.reestr_contract_223_fz_awarded USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_223_fz_commission_work_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_commission_work_okpd_id_start_date_idx ON public.reestr_contract_223_fz_commission_work USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_223_fz_commission_work_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_commission_work_status_id_idx ON public.reestr_contract_223_fz_commission_work USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_223_fz_completed_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_completed_okpd_id_start_date_idx ON public.reestr_contract_223_fz_completed USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_223_fz_completed_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_completed_status_id_idx ON public.reestr_contract_223_fz_completed USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_223_fz_unclear_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_unclear_okpd_id_start_date_idx ON public.reestr_contract_223_fz_unclear USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_223_fz_unclear_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_223_fz_unclear_status_id_idx ON public.reestr_contract_223_fz_unclear USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_44_fz_awarded_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_awarded_okpd_id_start_date_idx ON public.reestr_contract_44_fz_awarded USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_44_fz_awarded_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_awarded_status_id_idx ON public.reestr_contract_44_fz_awarded USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_44_fz_bad_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_bad_okpd_id_start_date_idx ON public.reestr_contract_44_fz_bad USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_44_fz_bad_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_bad_status_id_idx ON public.reestr_contract_44_fz_bad USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_44_fz_commission_work_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_commission_work_okpd_id_start_date_idx ON public.reestr_contract_44_fz_commission_work USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_44_fz_commission_work_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_commission_work_status_id_idx ON public.reestr_contract_44_fz_commission_work USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_44_fz_completed_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_completed_okpd_id_start_date_idx ON public.reestr_contract_44_fz_completed USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_44_fz_completed_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_completed_status_id_idx ON public.reestr_contract_44_fz_completed USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_44_fz_unclear_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_unclear_okpd_id_start_date_idx ON public.reestr_contract_44_fz_unclear USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_44_fz_unclear_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_unclear_status_id_idx ON public.reestr_contract_44_fz_unclear USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: reestr_contract_44_fz_unknown_okpd_id_start_date_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_unknown_okpd_id_start_date_idx ON public.reestr_contract_44_fz_unknown USING btree (okpd_id, start_date DESC);


--
-- Name: reestr_contract_44_fz_unknown_status_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX reestr_contract_44_fz_unknown_status_id_idx ON public.reestr_contract_44_fz_unknown USING btree (status_id) WHERE (status_id IS NOT NULL);


--
-- Name: route_histo_from_la_6ff81b_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX route_histo_from_la_6ff81b_idx ON public.route_history USING btree (from_lat, from_lon, to_lat, to_lon);


--
-- Name: route_histo_travel__ce8595_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX route_histo_travel__ce8595_idx ON public.route_history USING btree (travel_mode);


--
-- Name: route_histo_user_id_58c848_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX route_histo_user_id_58c848_idx ON public.route_history USING btree (user_id, date_time);


--
-- Name: route_history_user_id_c38083fe; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX route_history_user_id_c38083fe ON public.route_history USING btree (user_id);


--
-- Name: saved_searc_is_acti_af6ddd_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX saved_searc_is_acti_af6ddd_idx ON public.saved_searches USING btree (is_active, check_frequency, last_check_at);


--
-- Name: saved_searc_user_id_5cc902_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX saved_searc_user_id_5cc902_idx ON public.saved_searches USING btree (user_id, created_at);


--
-- Name: saved_searches_user_id_4b45091f; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX saved_searches_user_id_4b45091f ON public.saved_searches USING btree (user_id);


--
-- Name: silk_profile_queries_profile_id_a3d76db8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_profile_queries_profile_id_a3d76db8 ON public.silk_profile_queries USING btree (profile_id);


--
-- Name: silk_profile_queries_sqlquery_id_155df455; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_profile_queries_sqlquery_id_155df455 ON public.silk_profile_queries USING btree (sqlquery_id);


--
-- Name: silk_profile_request_id_7b81bd69; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_profile_request_id_7b81bd69 ON public.silk_profile USING btree (request_id);


--
-- Name: silk_profile_request_id_7b81bd69_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_profile_request_id_7b81bd69_like ON public.silk_profile USING btree (request_id varchar_pattern_ops);


--
-- Name: silk_request_id_5a356c4f_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_request_id_5a356c4f_like ON public.silk_request USING btree (id varchar_pattern_ops);


--
-- Name: silk_request_path_9f3d798e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_request_path_9f3d798e ON public.silk_request USING btree (path);


--
-- Name: silk_request_path_9f3d798e_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_request_path_9f3d798e_like ON public.silk_request USING btree (path varchar_pattern_ops);


--
-- Name: silk_request_start_time_1300bc58; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_request_start_time_1300bc58 ON public.silk_request USING btree (start_time);


--
-- Name: silk_request_view_name_68559f7b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_request_view_name_68559f7b ON public.silk_request USING btree (view_name);


--
-- Name: silk_request_view_name_68559f7b_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_request_view_name_68559f7b_like ON public.silk_request USING btree (view_name varchar_pattern_ops);


--
-- Name: silk_response_id_dda88710_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_response_id_dda88710_like ON public.silk_response USING btree (id varchar_pattern_ops);


--
-- Name: silk_response_request_id_1e8e2776_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_response_request_id_1e8e2776_like ON public.silk_response USING btree (request_id varchar_pattern_ops);


--
-- Name: silk_sqlquery_request_id_6f8f0527; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_sqlquery_request_id_6f8f0527 ON public.silk_sqlquery USING btree (request_id);


--
-- Name: silk_sqlquery_request_id_6f8f0527_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX silk_sqlquery_request_id_6f8f0527_like ON public.silk_sqlquery USING btree (request_id varchar_pattern_ops);


--
-- Name: subscriptio_expires_af5d7e_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptio_expires_af5d7e_idx ON public.subscriptions USING btree (expires_at);


--
-- Name: subscriptio_status_b3f3e1_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptio_status_b3f3e1_idx ON public.subscriptions USING btree (status, expires_at);


--
-- Name: subscriptio_user_id_8d58fd_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptio_user_id_8d58fd_idx ON public.subscriptions USING btree (user_id, status);


--
-- Name: subscriptions_expires_at_d15754f5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptions_expires_at_d15754f5 ON public.subscriptions USING btree (expires_at);


--
-- Name: subscriptions_status_541403ce; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptions_status_541403ce ON public.subscriptions USING btree (status);


--
-- Name: subscriptions_status_541403ce_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptions_status_541403ce_like ON public.subscriptions USING btree (status varchar_pattern_ops);


--
-- Name: subscriptions_user_id_599297d4; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptions_user_id_599297d4 ON public.subscriptions USING btree (user_id);


--
-- Name: subscriptions_yookassa_subscription_id_f2d7baf9_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX subscriptions_yookassa_subscription_id_f2d7baf9_like ON public.subscriptions USING btree (yookassa_subscription_id varchar_pattern_ops);


--
-- Name: team_member_member__03b135_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX team_member_member__03b135_idx ON public.team_members USING btree (member_id, is_active);


--
-- Name: team_member_team_id_1299bd_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX team_member_team_id_1299bd_idx ON public.team_members USING btree (team_id, is_active);


--
-- Name: team_members_member_id_49e20b96; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX team_members_member_id_49e20b96 ON public.team_members USING btree (member_id);


--
-- Name: team_members_team_id_eb8b893a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX team_members_team_id_eb8b893a ON public.team_members USING btree (team_id);


--
-- Name: tenders_category_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_category_idx ON public.tenders USING btree (category);


--
-- Name: tenders_code_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_code_idx ON public.tenders USING btree (code);


--
-- Name: tenders_customer_inn_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_customer_inn_idx ON public.tenders USING btree (customer_inn);


--
-- Name: tenders_deadline_at_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_deadline_at_idx ON public.tenders USING btree (deadline_at);


--
-- Name: tenders_deadline_status_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_deadline_status_idx ON public.tenders USING btree (deadline_at, status);


--
-- Name: tenders_external_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_external_id_idx ON public.tenders USING btree (external_id);


--
-- Name: tenders_nmck_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_nmck_idx ON public.tenders USING btree (nmck);


--
-- Name: tenders_platform_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_platform_idx ON public.tenders USING btree (platform);


--
-- Name: tenders_platform_status_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_platform_status_idx ON public.tenders USING btree (platform, status);


--
-- Name: tenders_published_at_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_published_at_idx ON public.tenders USING btree (published_at);


--
-- Name: tenders_region_category_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_region_category_idx ON public.tenders USING btree (region, category);


--
-- Name: tenders_region_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_region_idx ON public.tenders USING btree (region);


--
-- Name: tenders_search_vector_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_search_vector_idx ON public.tenders USING gin (search_vector);


--
-- Name: tenders_status_category_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_status_category_idx ON public.tenders USING btree (status, category);


--
-- Name: tenders_status_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_status_idx ON public.tenders USING btree (status);


--
-- Name: tenders_status_published_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_status_published_idx ON public.tenders USING btree (status, published_at);


--
-- Name: tenders_status_region_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX tenders_status_region_idx ON public.tenders USING btree (status, region);


--
-- Name: token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like ON public.token_blacklist_outstandingtoken USING btree (jti varchar_pattern_ops);


--
-- Name: token_blacklist_outstandingtoken_user_id_83bc629a; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX token_blacklist_outstandingtoken_user_id_83bc629a ON public.token_blacklist_outstandingtoken USING btree (user_id);


--
-- Name: unique_primary_mfa_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX unique_primary_mfa_device ON public.mfa_devices USING btree (user_id) WHERE is_primary;


--
-- Name: unique_user_filter; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX unique_user_filter ON public.stop_words_names USING btree (user_id, stop_word);


--
-- Name: uq_dpq_contract; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_dpq_contract ON public.document_processing_queue USING btree (contract_reg_number);


--
-- Name: user_achiev_user_id_40367f_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_achiev_user_id_40367f_idx ON public.user_achievements USING btree (user_id, unlocked_at);


--
-- Name: user_achievements_achievement_id_ecab25b8; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_achievements_achievement_id_ecab25b8 ON public.user_achievements USING btree (achievement_id);


--
-- Name: user_achievements_unlocked_at_643541f3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_achievements_unlocked_at_643541f3 ON public.user_achievements USING btree (unlocked_at);


--
-- Name: user_achievements_user_id_339ff42b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_achievements_user_id_339ff42b ON public.user_achievements USING btree (user_id);


--
-- Name: user_challe_challen_08dbdf_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challe_challen_08dbdf_idx ON public.user_challenges USING btree (challenge_id, completed_at);


--
-- Name: user_challe_user_id_4eea5f_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challe_user_id_4eea5f_idx ON public.user_challenges USING btree (user_id, reward_claimed);


--
-- Name: user_challe_user_id_542807_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challe_user_id_542807_idx ON public.user_challenges USING btree (user_id, completed_at);


--
-- Name: user_challenges_challenge_id_181ec5ed; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challenges_challenge_id_181ec5ed ON public.user_challenges USING btree (challenge_id);


--
-- Name: user_challenges_completed_at_f0da1a39; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challenges_completed_at_f0da1a39 ON public.user_challenges USING btree (completed_at);


--
-- Name: user_challenges_reward_claimed_ef9ea5bb; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challenges_reward_claimed_ef9ea5bb ON public.user_challenges USING btree (reward_claimed);


--
-- Name: user_challenges_user_id_5d98ab1b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_challenges_user_id_5d98ab1b ON public.user_challenges USING btree (user_id);


--
-- Name: user_creden_expires_28519e_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_creden_expires_28519e_idx ON public.user_credentials USING btree (expires_at);


--
-- Name: user_creden_user_id_4d83d1_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_creden_user_id_4d83d1_idx ON public.user_credentials USING btree (user_id, credential_type);


--
-- Name: user_credentials_user_id_49daef2d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_credentials_user_id_49daef2d ON public.user_credentials USING btree (user_id);


--
-- Name: user_learni_materia_4e88c3_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_learni_materia_4e88c3_idx ON public.user_learning_progress USING btree (material_id, is_completed);


--
-- Name: user_learni_user_id_ff57d7_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_learni_user_id_ff57d7_idx ON public.user_learning_progress USING btree (user_id, is_completed);


--
-- Name: user_learning_progress_completed_at_f37647a2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_learning_progress_completed_at_f37647a2 ON public.user_learning_progress USING btree (completed_at);


--
-- Name: user_learning_progress_is_completed_a6a04045; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_learning_progress_is_completed_a6a04045 ON public.user_learning_progress USING btree (is_completed);


--
-- Name: user_learning_progress_material_id_1f6e07c2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_learning_progress_material_id_1f6e07c2 ON public.user_learning_progress USING btree (material_id);


--
-- Name: user_learning_progress_user_id_6d552368; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_learning_progress_user_id_6d552368 ON public.user_learning_progress USING btree (user_id);


--
-- Name: user_locati_user_id_cf0030_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_locati_user_id_cf0030_idx ON public.user_locations USING btree (user_id, is_default);


--
-- Name: user_locations_user_id_fcdc61c5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX user_locations_user_id_fcdc61c5 ON public.user_locations USING btree (user_id);


--
-- Name: users_blogp_categor_0d9aec_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_blogp_categor_0d9aec_idx ON public.users_blogpost USING btree (category, status);


--
-- Name: users_blogp_slug_124c22_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_blogp_slug_124c22_idx ON public.users_blogpost USING btree (slug);


--
-- Name: users_blogp_status_b63dda_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_blogp_status_b63dda_idx ON public.users_blogpost USING btree (status, published_at);


--
-- Name: users_blogpost_slug_1bbdda48_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_blogpost_slug_1bbdda48_like ON public.users_blogpost USING btree (slug varchar_pattern_ops);


--
-- Name: users_company_6113b7_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_company_6113b7_idx ON public.users USING btree (company_type);


--
-- Name: users_company_type_586704ed; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_company_type_586704ed ON public.users USING btree (company_type);


--
-- Name: users_company_type_586704ed_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_company_type_586704ed_like ON public.users USING btree (company_type varchar_pattern_ops);


--
-- Name: users_created_6541e9_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_created_6541e9_idx ON public.users USING btree (created_at);


--
-- Name: users_email_0ea73cca_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_email_0ea73cca_like ON public.users USING btree (email varchar_pattern_ops);


--
-- Name: users_email_4b85f2_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_email_4b85f2_idx ON public.users USING btree (email);


--
-- Name: users_groups_group_id_2f3517aa; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_groups_group_id_2f3517aa ON public.users_groups USING btree (group_id);


--
-- Name: users_groups_user_id_f500bee5; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_groups_user_id_f500bee5 ON public.users_groups USING btree (user_id);


--
-- Name: users_subscri_8ce858_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_subscri_8ce858_idx ON public.users USING btree (subscription_tier);


--
-- Name: users_subscription_tier_a0b43c40; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_subscription_tier_a0b43c40 ON public.users USING btree (subscription_tier);


--
-- Name: users_subscription_tier_a0b43c40_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_subscription_tier_a0b43c40_like ON public.users USING btree (subscription_tier varchar_pattern_ops);


--
-- Name: users_telegra_613f9c_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_telegra_613f9c_idx ON public.users USING btree (telegram_user_id);


--
-- Name: users_user_permissions_permission_id_6d08dcd2; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_user_permissions_permission_id_6d08dcd2 ON public.users_user_permissions USING btree (permission_id);


--
-- Name: users_user_permissions_user_id_92473840; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_user_permissions_user_id_92473840 ON public.users_user_permissions USING btree (user_id);


--
-- Name: users_username_e8658fc8_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX users_username_e8658fc8_like ON public.users USING btree (username varchar_pattern_ops);


--
-- Name: ux_contractor_role_contractor_id_role; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_contractor_role_contractor_id_role ON public.contractor_role USING btree (contractor_id, role);


--
-- Name: ux_customer_role_customer_id_role; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_customer_role_customer_id_role ON public.customer_role USING btree (customer_id, role);


--
-- Name: ux_object_type_classifications_binding; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_object_type_classifications_binding ON public.crm_object_type_classifications USING btree (COALESCE(object_uid, ''::text), COALESCE(tender_id, ('-1'::integer)::bigint), COALESCE(contract_number, ''::text), COALESCE(registry_type, ''::text), COALESCE(source_table, ''::text));


--
-- Name: webinar_reg_user_id_dc7fc8_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinar_reg_user_id_dc7fc8_idx ON public.webinar_registrations USING btree (user_id, registered_at);


--
-- Name: webinar_reg_webinar_e73b73_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinar_reg_webinar_e73b73_idx ON public.webinar_registrations USING btree (webinar_id, registered_at);


--
-- Name: webinar_registrations_attended_5bb32c87; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinar_registrations_attended_5bb32c87 ON public.webinar_registrations USING btree (attended);


--
-- Name: webinar_registrations_user_id_2772d66c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinar_registrations_user_id_2772d66c ON public.webinar_registrations USING btree (user_id);


--
-- Name: webinar_registrations_webinar_id_7b1b461d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinar_registrations_webinar_id_7b1b461d ON public.webinar_registrations USING btree (webinar_id);


--
-- Name: webinars_categor_0537e6_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_categor_0537e6_idx ON public.webinars USING btree (category, status);


--
-- Name: webinars_category_3968eb0d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_category_3968eb0d ON public.webinars USING btree (category);


--
-- Name: webinars_category_3968eb0d_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_category_3968eb0d_like ON public.webinars USING btree (category varchar_pattern_ops);


--
-- Name: webinars_is_feat_0a0392_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_is_feat_0a0392_idx ON public.webinars USING btree (is_featured, priority);


--
-- Name: webinars_is_featured_80f00c48; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_is_featured_80f00c48 ON public.webinars USING btree (is_featured);


--
-- Name: webinars_priority_010f94a3; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_priority_010f94a3 ON public.webinars USING btree (priority);


--
-- Name: webinars_scheduled_at_8b2f873e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_scheduled_at_8b2f873e ON public.webinars USING btree (scheduled_at);


--
-- Name: webinars_slug_c2c855a2_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_slug_c2c855a2_like ON public.webinars USING btree (slug varchar_pattern_ops);


--
-- Name: webinars_status_018e6d_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_status_018e6d_idx ON public.webinars USING btree (status, scheduled_at);


--
-- Name: webinars_status_c080c903; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_status_c080c903 ON public.webinars USING btree (status);


--
-- Name: webinars_status_c080c903_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX webinars_status_c080c903_like ON public.webinars USING btree (status varchar_pattern_ops);


--
-- Name: xp_transact_reason_b266e1_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transact_reason_b266e1_idx ON public.xp_transactions USING btree (reason);


--
-- Name: xp_transact_user_id_92484a_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transact_user_id_92484a_idx ON public.xp_transactions USING btree (user_id, created_at);


--
-- Name: xp_transactions_created_at_92492e3d; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transactions_created_at_92492e3d ON public.xp_transactions USING btree (created_at);


--
-- Name: xp_transactions_reason_fcfb0fdd; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transactions_reason_fcfb0fdd ON public.xp_transactions USING btree (reason);


--
-- Name: xp_transactions_reason_fcfb0fdd_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transactions_reason_fcfb0fdd_like ON public.xp_transactions USING btree (reason varchar_pattern_ops);


--
-- Name: xp_transactions_related_achievement_id_385dc0b9; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transactions_related_achievement_id_385dc0b9 ON public.xp_transactions USING btree (related_achievement_id);


--
-- Name: xp_transactions_user_id_5cebad00; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX xp_transactions_user_id_5cebad00 ON public.xp_transactions USING btree (user_id);


--
-- Name: application_forms application_forms_template_id_cfdb4430_fk_applicati; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_forms
    ADD CONSTRAINT application_forms_template_id_cfdb4430_fk_applicati FOREIGN KEY (template_id) REFERENCES public.application_templates(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: calibration_metrics calibration_metrics_calibration_weights__7ff625a8_fk_calibrati; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.calibration_metrics
    ADD CONSTRAINT calibration_metrics_calibration_weights__7ff625a8_fk_calibrati FOREIGN KEY (calibration_weights_id) REFERENCES public.calibration_weights(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: collection_codes_okpd collection_codes_okpd_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.collection_codes_okpd
    ADD CONSTRAINT collection_codes_okpd_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.collection_codes_okpd(id) ON DELETE CASCADE;


--
-- Name: contact_link contact_link_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact_link
    ADD CONSTRAINT contact_link_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contact(id);


--
-- Name: contact_link contact_link_contractor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact_link
    ADD CONSTRAINT contact_link_contractor_id_fkey FOREIGN KEY (contractor_id) REFERENCES public.contractor(id);


--
-- Name: contact_link contact_link_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contact_link
    ADD CONSTRAINT contact_link_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: contractor_role contractor_role_contractor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contractor_role
    ADD CONSTRAINT contractor_role_contractor_id_fkey FOREIGN KEY (contractor_id) REFERENCES public.contractor(id);


--
-- Name: customer_role customer_role_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customer_role
    ADD CONSTRAINT customer_role_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: key_words_names_documentations fk_keywords_setting; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names_documentations
    ADD CONSTRAINT fk_keywords_setting FOREIGN KEY (setting_id) REFERENCES public.setting_options_from_users(id);


--
-- Name: okpd_from_users fk_okpd_setting; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_from_users
    ADD CONSTRAINT fk_okpd_setting FOREIGN KEY (setting_id) REFERENCES public.setting_options_from_users(id);


--
-- Name: reestr_contract_223_fz fk_reestr_contract_223_fz_status_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz
    ADD CONSTRAINT fk_reestr_contract_223_fz_status_id FOREIGN KEY (status_id) REFERENCES public.tender_statuses(id);


--
-- Name: reestr_contract_44_fz fk_reestr_contract_44_fz_status_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz
    ADD CONSTRAINT fk_reestr_contract_44_fz_status_id FOREIGN KEY (status_id) REFERENCES public.tender_statuses(id);


--
-- Name: stop_words_names fk_stopwords_setting; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stop_words_names
    ADD CONSTRAINT fk_stopwords_setting FOREIGN KEY (setting_id) REFERENCES public.setting_options_from_users(id);


--
-- Name: integrations integrations_user_id_8162b4e4_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.integrations
    ADD CONSTRAINT integrations_user_id_8162b4e4_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: invoices invoices_payment_id_d20b1255_fk_payments_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_payment_id_d20b1255_fk_payments_id FOREIGN KEY (payment_id) REFERENCES public.payments(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: key_words_names_documentations key_words_names_documentations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names_documentations
    ADD CONSTRAINT key_words_names_documentations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: key_words_names key_words_names_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.key_words_names
    ADD CONSTRAINT key_words_names_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: links_documentation_44_fz links_documentation_44_fz_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_44_fz
    ADD CONSTRAINT links_documentation_44_fz_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.reestr_contract_44_fz(id) ON DELETE CASCADE;


--
-- Name: links_documentation_615_pp_commission_work links_documentation_615_pp_commission_work_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_615_pp_commission_work
    ADD CONSTRAINT links_documentation_615_pp_commission_work_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.reestr_contract_615_pp_commission_work(id) ON DELETE CASCADE;


--
-- Name: links_documentation_615_pp links_documentation_615_pp_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.links_documentation_615_pp
    ADD CONSTRAINT links_documentation_615_pp_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.reestr_contract_615_pp(id) ON DELETE CASCADE;


--
-- Name: okpd_categories okpd_categories_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_categories
    ADD CONSTRAINT okpd_categories_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: okpd_from_users okpd_from_users_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_from_users
    ADD CONSTRAINT okpd_from_users_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.okpd_categories(id) ON DELETE SET NULL;


--
-- Name: okpd_from_users okpd_from_users_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.okpd_from_users
    ADD CONSTRAINT okpd_from_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: payments payments_subscription_id_956d9d05_fk_subscriptions_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_subscription_id_956d9d05_fk_subscriptions_id FOREIGN KEY (subscription_id) REFERENCES public.subscriptions(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: reestr_contract_223_fz reestr_contract_223_fz_contractor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz
    ADD CONSTRAINT reestr_contract_223_fz_contractor_id_fkey FOREIGN KEY (contractor_id) REFERENCES public.contractor(id);


--
-- Name: reestr_contract_223_fz reestr_contract_223_fz_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz
    ADD CONSTRAINT reestr_contract_223_fz_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: reestr_contract_223_fz reestr_contract_223_fz_okpd_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz
    ADD CONSTRAINT reestr_contract_223_fz_okpd_id_fkey FOREIGN KEY (okpd_id) REFERENCES public.collection_codes_okpd(id);


--
-- Name: reestr_contract_223_fz reestr_contract_223_fz_trading_platform_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_223_fz
    ADD CONSTRAINT reestr_contract_223_fz_trading_platform_id_fkey FOREIGN KEY (trading_platform_id) REFERENCES public.trading_platform(id);


--
-- Name: reestr_contract_44_fz reestr_contract_44_fz_contractor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz
    ADD CONSTRAINT reestr_contract_44_fz_contractor_id_fkey FOREIGN KEY (contractor_id) REFERENCES public.contractor(id);


--
-- Name: reestr_contract_44_fz reestr_contract_44_fz_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz
    ADD CONSTRAINT reestr_contract_44_fz_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: reestr_contract_44_fz reestr_contract_44_fz_okpd_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz
    ADD CONSTRAINT reestr_contract_44_fz_okpd_id_fkey FOREIGN KEY (okpd_id) REFERENCES public.collection_codes_okpd(id);


--
-- Name: reestr_contract_44_fz reestr_contract_44_fz_trading_platform_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_44_fz
    ADD CONSTRAINT reestr_contract_44_fz_trading_platform_id_fkey FOREIGN KEY (trading_platform_id) REFERENCES public.trading_platform(id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_contractor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_contractor_id_fkey FOREIGN KEY (contractor_id) REFERENCES public.contractor(id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_okpd_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_okpd_id_fkey FOREIGN KEY (okpd_id) REFERENCES public.collection_codes_okpd(id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.region(id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_status_id_fkey FOREIGN KEY (status_id) REFERENCES public.tender_statuses(id);


--
-- Name: reestr_contract_615_pp_commission_work reestr_contract_615_pp_commission_work_trading_platform_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_commission_work
    ADD CONSTRAINT reestr_contract_615_pp_commission_work_trading_platform_id_fkey FOREIGN KEY (trading_platform_id) REFERENCES public.trading_platform(id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_contractor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_contractor_id_fkey FOREIGN KEY (contractor_id) REFERENCES public.contractor(id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: reestr_contract_615_pp_nspd_match reestr_contract_615_pp_nspd_match_contract_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp_nspd_match
    ADD CONSTRAINT reestr_contract_615_pp_nspd_match_contract_id_fkey FOREIGN KEY (contract_id) REFERENCES public.reestr_contract_615_pp(id) ON DELETE CASCADE;


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_okpd_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_okpd_id_fkey FOREIGN KEY (okpd_id) REFERENCES public.collection_codes_okpd(id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.region(id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_status_id_fkey FOREIGN KEY (status_id) REFERENCES public.tender_statuses(id);


--
-- Name: reestr_contract_615_pp reestr_contract_615_pp_trading_platform_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reestr_contract_615_pp
    ADD CONSTRAINT reestr_contract_615_pp_trading_platform_id_fkey FOREIGN KEY (trading_platform_id) REFERENCES public.trading_platform(id);


--
-- Name: sales_deals sales_deals_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales_deals
    ADD CONSTRAINT sales_deals_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.sales_pipeline_stages(id);


--
-- Name: silk_profile_queries silk_profile_queries_profile_id_a3d76db8_fk_silk_profile_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_profile_queries
    ADD CONSTRAINT silk_profile_queries_profile_id_a3d76db8_fk_silk_profile_id FOREIGN KEY (profile_id) REFERENCES public.silk_profile(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: silk_profile_queries silk_profile_queries_sqlquery_id_155df455_fk_silk_sqlquery_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_profile_queries
    ADD CONSTRAINT silk_profile_queries_sqlquery_id_155df455_fk_silk_sqlquery_id FOREIGN KEY (sqlquery_id) REFERENCES public.silk_sqlquery(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: silk_profile silk_profile_request_id_7b81bd69_fk_silk_request_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_profile
    ADD CONSTRAINT silk_profile_request_id_7b81bd69_fk_silk_request_id FOREIGN KEY (request_id) REFERENCES public.silk_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: silk_response silk_response_request_id_1e8e2776_fk_silk_request_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_response
    ADD CONSTRAINT silk_response_request_id_1e8e2776_fk_silk_request_id FOREIGN KEY (request_id) REFERENCES public.silk_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: silk_sqlquery silk_sqlquery_request_id_6f8f0527_fk_silk_request_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.silk_sqlquery
    ADD CONSTRAINT silk_sqlquery_request_id_6f8f0527_fk_silk_request_id FOREIGN KEY (request_id) REFERENCES public.silk_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: stop_words_names stop_words_names_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stop_words_names
    ADD CONSTRAINT stop_words_names_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: team_members team_members_member_id_49e20b96_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_member_id_49e20b96_fk_users_id FOREIGN KEY (member_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: team_members team_members_team_id_eb8b893a_fk_teams_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_team_id_eb8b893a_fk_teams_id FOREIGN KEY (team_id) REFERENCES public.teams(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: teams teams_owner_id_d02bfe57_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_owner_id_d02bfe57_fk_users_id FOREIGN KEY (owner_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: tender_document_match_details tender_document_match_details_match_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_document_match_details
    ADD CONSTRAINT tender_document_match_details_match_id_fkey FOREIGN KEY (match_id) REFERENCES public.tender_document_matches(id) ON DELETE CASCADE;


--
-- Name: tender_plan_2020 tender_plan_2020_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020
    ADD CONSTRAINT tender_plan_2020_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(id);


--
-- Name: tender_plan_2020_position tender_plan_2020_position_contract_44_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_position
    ADD CONSTRAINT tender_plan_2020_position_contract_44_id_fkey FOREIGN KEY (contract_44_id) REFERENCES public.reestr_contract_44_fz(id);


--
-- Name: tender_plan_2020_position tender_plan_2020_position_okpd2_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_position
    ADD CONSTRAINT tender_plan_2020_position_okpd2_id_fkey FOREIGN KEY (okpd2_id) REFERENCES public.collection_codes_okpd(id);


--
-- Name: tender_plan_2020_position tender_plan_2020_position_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020_position
    ADD CONSTRAINT tender_plan_2020_position_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.tender_plan_2020(id) ON DELETE CASCADE;


--
-- Name: tender_plan_2020 tender_plan_2020_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tender_plan_2020
    ADD CONSTRAINT tender_plan_2020_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.region(id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk FOREIGN KEY (token_id) REFERENCES public.token_blacklist_outstandingtoken(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: user_achievements user_achievements_achievement_id_ecab25b8_fk_achievements_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_achievements
    ADD CONSTRAINT user_achievements_achievement_id_ecab25b8_fk_achievements_id FOREIGN KEY (achievement_id) REFERENCES public.achievements(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: user_challenges user_challenges_challenge_id_181ec5ed_fk_challenges_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_challenges
    ADD CONSTRAINT user_challenges_challenge_id_181ec5ed_fk_challenges_id FOREIGN KEY (challenge_id) REFERENCES public.challenges(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: user_credentials user_credentials_user_id_49daef2d_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_credentials
    ADD CONSTRAINT user_credentials_user_id_49daef2d_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: user_learning_progress user_learning_progre_material_id_1f6e07c2_fk_learning_; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_learning_progress
    ADD CONSTRAINT user_learning_progre_material_id_1f6e07c2_fk_learning_ FOREIGN KEY (material_id) REFERENCES public.learning_materials(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users_groups users_groups_user_id_f500bee5_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_user_id_f500bee5_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users_user_permissions users_user_permissions_user_id_92473840_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissions_user_id_92473840_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: webinar_registrations webinar_registrations_webinar_id_7b1b461d_fk_webinars_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.webinar_registrations
    ADD CONSTRAINT webinar_registrations_webinar_id_7b1b461d_fk_webinars_id FOREIGN KEY (webinar_id) REFERENCES public.webinars(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: xp_transactions xp_transactions_related_achievement__385dc0b9_fk_achieveme; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.xp_transactions
    ADD CONSTRAINT xp_transactions_related_achievement__385dc0b9_fk_achieveme FOREIGN KEY (related_achievement_id) REFERENCES public.achievements(id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

\unrestrict mZrRa0G49L5O3aOmP51nA5OwJ6zbObrGWKuU2nnC7fgQTs1UdW593A4sDqbuZXU

