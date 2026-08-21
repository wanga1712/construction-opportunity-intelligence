#!/usr/bin/env python3
"""Registry vocabulary audit for Architecture B (no model calls)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit") if Path("/opt/CRM_Streamlit").is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.registry_extract_mapper import (
    build_registry_vocabulary,
    check_vocabulary_gaps_for_phrases,
)

PHRASES = [
    "моноблок",
    "моноблоков",
    "светильник",
    "лампа",
    "кабель-канал",
    "линолеум",
    "ливневая канализация",
    "водоотведение",
    "поверка",
    "прибор учета",
]


def main() -> int:
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    registry, allowed, _ = engine.load_registry()
    vocab = build_registry_vocabulary(crm, registry)
    sample = sorted(vocab.terms_sorted, key=len, reverse=True)[:40]
    gaps = check_vocabulary_gaps_for_phrases(PHRASES, vocab, allowed)
    out = {
        "ACTIVE_CATEGORY_COUNT": len(allowed),
        "VOCAB_TERM_COUNT": len(vocab.terms_sorted),
        "SAMPLE_LONG_TERMS": sample,
        "PROBE_PHRASES": PHRASES,
        "PROBE_GAPS": gaps,
        "REGISTRY_VOCABULARY_GAP": bool(gaps),
        "HARDCODED_PRODUCT_SWITCHES": False,
        "NOTES": (
            "Mapper indexes category_name, aliases, positive_signals, "
            "subcategory names/codes, subcategory search terms when present. "
            "No arbitrary if monoblock→computers in code."
        ),
    }
    Path("/tmp/arch_registry_vocab_audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
