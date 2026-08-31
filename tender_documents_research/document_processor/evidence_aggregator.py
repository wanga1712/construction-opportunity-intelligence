from typing import List, Dict, Any
from document_processor.dto import FileProcessResult, EvidenceResult

class EvidenceAggregator:
    @staticmethod
    def aggregate(files: List[FileProcessResult]) -> List[EvidenceResult]:
        """
        Aggregates match details from all processed files into a single evidence list.
        
        SAFETY BARRIER:
        Only match details with validation_status == 'CONFIRMED' may contribute to
        positive EvidenceResult. Raw, UNKNOWN, PENDING, or REJECTED matches are
        strictly excluded from confirmed factual evidence.
        """
        cat_evidence = {}
        for f in files:
            for m in f.matches:
                for d in m.details:
                    val_status = str(getattr(d, "validation_status", "UNKNOWN") or "UNKNOWN").upper()
                    if val_status != "CONFIRMED":
                        continue

                    cat = d.category_code
                    if cat not in cat_evidence:
                        cat_evidence[cat] = {
                            "score": 0.0,
                            "count": 0,
                            "methods": set(),
                            "versions": set(),
                        }
                    cat_evidence[cat]["score"] = max(cat_evidence[cat]["score"], float(d.score))
                    cat_evidence[cat]["count"] += 1
                    if getattr(d, "validation_method", None):
                        cat_evidence[cat]["methods"].add(str(d.validation_method))
                    if getattr(d, "validator_version", None):
                        cat_evidence[cat]["versions"].add(str(d.validator_version))

        evidence_results = []
        for cat, ev in cat_evidence.items():
            val_method = ",".join(sorted(ev["methods"])) if ev["methods"] else "confirmed_v1"
            val_ver = ",".join(sorted(ev["versions"])) if ev["versions"] else "v1"
            evidence_results.append(EvidenceResult(
                category_code=cat,
                evidence_score=ev["score"],
                match_count=ev["count"],
                next_stage="STRUCTURED_EXTRACTION_PENDING",
                validation_status="CONFIRMED",
                validation_version=val_ver,
                validation_method=val_method,
            ))

        return evidence_results

