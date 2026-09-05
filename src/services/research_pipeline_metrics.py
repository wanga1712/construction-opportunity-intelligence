from typing import Dict, Any, List
import pandas as pd
from database_work.database_connection import DatabaseManager

class ResearchPipelineMetrics:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_queue_stats(self) -> Dict[str, int]:
        sql = "SELECT status, count(*) FROM document_processing_queue GROUP BY status;"
        rows = self.db.fetch_all(sql, db_alias='document_intelligence')
        res = {
            'waiting_total': 0,
            'processing_total': 0,
            'completed_total': 0,
            'failed_total': 0,
            'no_links_total': 0,
        }
        if not rows: return res
        for r in rows:
            st = r['status']
            c = r['count']
            if st in ('PENDING', 'PRE_RESEARCH_WAITING'):
                res['waiting_total'] += c
            elif st == 'PROCESSING':
                res['processing_total'] += c
            elif st == 'COMPLETED':
                res['completed_total'] += c
            elif st == 'FAILED':
                res['failed_total'] += c
            elif st == 'NO_LINKS':
                res['no_links_total'] += c
        return res

    def get_band_backlog(self) -> Dict[str, int]:
        sql = """
        SELECT COALESCE(research_prior_band, 'UNSCORED') as band, count(*)
        FROM document_processing_queue
        WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING')
        GROUP BY band;
        """
        rows = self.db.fetch_all(sql, db_alias='document_intelligence')
        res = {'GOLD': 0, 'SILVER': 0, 'BRONZE': 0, 'WOOD': 0, 'UNSCORED': 0}
        if rows:
            for r in rows:
                if r['band'] in res:
                    res[r['band']] = r['count']
        return res

    def get_time_window_stats(self, hours: int) -> Dict[str, int]:
        sql = f"""
        SELECT 
            COUNT(*) as claimed_total,
            COUNT(CASE WHEN research_prior_band = 'GOLD' THEN 1 END) as claimed_gold,
            COUNT(CASE WHEN research_prior_band = 'SILVER' THEN 1 END) as claimed_silver,
            COUNT(CASE WHEN research_prior_band = 'BRONZE' THEN 1 END) as claimed_bronze,
            COUNT(CASE WHEN research_prior_band = 'WOOD' THEN 1 END) as claimed_wood,
            COUNT(CASE WHEN research_prior_band IS NULL OR research_prior_band = 'UNSCORED' THEN 1 END) as claimed_unscored,
            COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed_total,
            COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_total,
            COUNT(CASE WHEN status = 'NO_LINKS' THEN 1 END) as no_links_total
        FROM document_processing_queue
        WHERE started_at >= NOW() - INTERVAL '{hours} hours'
        """
        rows = self.db.fetch_all(sql, db_alias='document_intelligence')
        if not rows:
            return {}
        return dict(rows[0])

    def get_fresh_outcomes(self) -> Dict[str, Any]:
        # Based on results table. Simplified for observability.
        return {
            'DEFINITIVE_TOTAL': 0,
            'POSITIVE': 0,
            'SAFE_NEGATIVE': 0,
            'UNRESOLVED': 0,
            'GOLD_N': 0, 'GOLD_HITS': 0,
            'SILVER_N': 0, 'SILVER_HITS': 0,
            'BRONZE_N': 0, 'BRONZE_HITS': 0,
            'WOOD_N': 0, 'WOOD_HITS': 0,
        }

    def get_recent_results(self, limit=50) -> List[Dict[str, Any]]:
        sql = f"""
        SELECT 
            id as queue_id,
            procurement_id,
            queue_lane,
            research_prior_band,
            research_prior_score,
            status as terminal_status,
            completed_at,
            last_error as technical_error
        FROM document_processing_queue
        WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
        ORDER BY completed_at DESC NULLS LAST
        LIMIT {limit};
        """
        rows = self.db.fetch_all(sql, db_alias='document_intelligence')
        return [dict(r) for r in rows] if rows else []
