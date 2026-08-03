"""Salesforce record-page CSS used by global Streamlit styles."""

SALESFORCE_STYLES = """
        /* Salesforce record page */
        .sf-record-title {{
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--crm-text);
            margin: 0 0 0.35rem 0;
            line-height: 1.35;
        }}
        .sf-record-ico {{
            margin-right: 0.35rem;
            font-size: 1.1rem;
        }}
        .sf-section-title {{
            font-size: 0.82rem;
            font-weight: 700;
            color: var(--crm-text);
            margin: 0 0 0.5rem 0;
            padding-bottom: 0.25rem;
            border-bottom: 1px solid var(--crm-border-soft);
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }}
        .sf-section-ico {{ font-size: 0.95rem; line-height: 1; }}
        .sf-ico {{ margin-right: 0.25rem; font-size: 0.85em; line-height: 1; }}
        .sf-badge .sf-ico {{ margin-right: 0.2rem; }}
        .sf-metric {{
            background: var(--crm-card);
            border: 1px solid var(--crm-border);
            border-radius: 0.45rem;
            padding: 0.4rem 0.55rem;
            min-height: 2.6rem;
        }}
        .sf-metric-label {{
            font-size: 0.62rem;
            font-weight: 600;
            color: var(--crm-muted-2);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            line-height: 1.2;
            margin-bottom: 2px;
        }}
        .sf-metric-value {{
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--crm-text);
            line-height: 1.25;
            word-break: break-word;
        }}
        .sf-badge {{
            display: inline-block;
            background: var(--crm-chip-bg);
            color: var(--crm-chip-text);
            border: 1px solid rgba(1,118,211,0.28);
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 0.72rem;
            font-weight: 600;
            margin-right: 6px;
            margin-bottom: 4px;
        }}
        .sf-field {{ margin-bottom: 0.65rem; }}
        .sf-field-label {{
            font-size: 0.68rem;
            font-weight: 600;
            color: var(--crm-muted-2);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 2px;
        }}
        .sf-field-value {{
            font-size: 0.88rem;
            color: var(--crm-text);
            line-height: 1.35;
            word-break: break-word;
        }}
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p {{
            font-size: 0.82rem !important;
            font-weight: 600 !important;
        }}
"""
