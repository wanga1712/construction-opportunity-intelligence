#!/usr/bin/env python3
"""Audit repository cleanliness and classify scratch files."""

import os
from pathlib import Path
from typing import Dict, List, Any

def audit_repository(root_dir: Path) -> Dict[str, Any]:
    scratch_dir = root_dir / "scratch"
    classification = {
        "TOTAL": 0,
        "PRODUCTION_REQUIRED": 0,
        "TEST_REQUIRED": 0,
        "FORENSIC_REFERENCE": 0,
        "TEMPORARY": 0,
        "ACCIDENTAL_RUNTIME": 0,
        "FILES": []
    }
    
    if not scratch_dir.exists():
        return classification
        
    for p in scratch_dir.rglob("*"):
        if p.is_file():
            classification["TOTAL"] += 1
            rel = str(p.relative_to(root_dir))
            
            # Classification rules
            if any(k in rel for k in ["reconciliation", "s13_tree", "forensic", "snapshot"]):
                cat = "FORENSIC_REFERENCE"
            elif any(k in rel for k in ["test_", "verify_", "check_"]):
                cat = "TEST_REQUIRED"
            elif rel.endswith(".py") or rel.endswith(".sql") or rel.endswith(".sh"):
                cat = "TEMPORARY"
            else:
                cat = "ACCIDENTAL_RUNTIME"
                
            classification[cat] += 1
            classification["FILES"].append({"path": rel, "category": cat})
            
    return classification

if __name__ == "__main__":
    root = Path(__file__).parent.parent.parent
    res = audit_repository(root)
    print(f"Repository Audit: Total scratch files={res['TOTAL']}")
    print(f"  PRODUCTION_REQUIRED: {res['PRODUCTION_REQUIRED']}")
    print(f"  TEST_REQUIRED: {res['TEST_REQUIRED']}")
    print(f"  FORENSIC_REFERENCE: {res['FORENSIC_REFERENCE']}")
    print(f"  TEMPORARY: {res['TEMPORARY']}")
    print(f"  ACCIDENTAL_RUNTIME: {res['ACCIDENTAL_RUNTIME']}")
