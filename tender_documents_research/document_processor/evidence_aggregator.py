from typing import List, Dict, Any
from document_processor.dto import FileProcessResult, EvidenceResult

class EvidenceAggregator:
    @staticmethod
    def aggregate(files: List[FileProcessResult]) -> List[EvidenceResult]:
        """
        Aggregates match details from all processed files into a single evidence list.
        """
        cat_evidence = {}
        for f in files:
            for m in f.matches:
                if m.category_code not in cat_evidence:
                    cat_evidence[m.category_code] = {"score": 0.0, "count": 0}
                cat_evidence[m.category_code]["score"] = max(cat_evidence[m.category_code]["score"], m.score)
                cat_evidence[m.category_code]["count"] += m.match_count

        evidence_results = []
        for cat, ev in cat_evidence.items():
            evidence_results.append(EvidenceResult(
                category_code=cat,
                evidence_score=ev["score"],
                match_count=ev["count"]
            ))

        return evidence_results
