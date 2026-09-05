import streamlit as st
import pandas as pd
from src.services.research_pipeline_metrics import ResearchPipelineMetrics
from database_work.database_connection import DatabaseManager

def render():
    st.title("Research Pipeline Observability")
    
    db = DatabaseManager.get_instance()
    if not db:
        st.error("No DB connection")
        return
        
    svc = ResearchPipelineMetrics(db)
    
    st.header("Top Summary")
    stats = svc.get_queue_stats()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Waiting", stats.get('waiting_total', 0))
    col2.metric("Processing", stats.get('processing_total', 0))
    col3.metric("Completed", stats.get('completed_total', 0))
    col4.metric("Failed", stats.get('failed_total', 0))
    
    st.header("Band Backlog")
    bands = svc.get_band_backlog()
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.metric("GOLD", bands.get('GOLD', 0))
    bc2.metric("SILVER", bands.get('SILVER', 0))
    bc3.metric("BRONZE", bands.get('BRONZE', 0))
    bc4.metric("WOOD", bands.get('WOOD', 0))
    
    st.header("Throughput (Last 24h)")
    t24 = svc.get_time_window_stats(24)
    if t24:
        st.write(f"Claimed: {t24.get('claimed_total', 0)}")
        st.write(f"Completed: {t24.get('completed_total', 0)}")
    
    st.header("Recent Results")
    recent = svc.get_recent_results()
    if recent:
        st.dataframe(pd.DataFrame(recent))
    else:
        st.write("No recent results.")
