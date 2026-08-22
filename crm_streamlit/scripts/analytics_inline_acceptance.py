#!/usr/bin/env python3
"""Read-only real-route acceptance for inline analytics cards."""
import json, os, sys
from pathlib import Path
root=Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit")); os.chdir(root); sys.path[:0]=[str(root), "/opt/pythonProject89"]
from dotenv import load_dotenv
load_dotenv(root/".env", override=True)
from streamlit.testing.v1 import AppTest
from src.ui.components.analytics_v2 import annotation_card

calls=[]; real=annotation_card.load_annotation_card_view
def counted(*args, **kwargs): calls.append(args[0]); return real(*args, **kwargs)
annotation_card.load_annotation_card_view=counted
at=AppTest.from_file("app.py", default_timeout=240); at.session_state["nav_page"]="objects_v2"; at.run(timeout=240)
stage=next(r for r in at.radio if "Идут торги" in list(r.options)); stage.set_value("Идут торги"); at.run(timeout=240)
labels=[str(r.label) for r in at.radio]; options=[list(r.options) for r in at.radio]
buttons=[str(b.label) for b in at.button]
metrics=[str(m.label) for m in at.metric]
initial_calls=len(calls)
section=next(r for r in at.radio if r.label=="Раздел карточки")
before_sections=sum(1 for r in at.radio if r.label=="Раздел карточки")
section.set_value("Документы"); at.run(timeout=240)
out={
 "inline_cards": before_sections,
 "open_visible": "Открыть карточку" in buttons,
 "back_visible": any("Назад к списку" in b for b in buttons),
 "annotation_filter": any(any(str(v).startswith("Все ·") for v in opts) and any(str(v).startswith("Неинтересные ·") for v in opts) for opts in options),
 "summary": all(x in metrics for x in ("НМЦК","Приём заявок до","Источник")),
 "initial_resolver_calls": initial_calls,
 "one_documents_resolver_calls": len(calls)-initial_calls,
 "cards_remain": sum(1 for r in at.radio if r.label=="Раздел карточки"),
 "document_links": len(at.get("link_button")),
 "exceptions": [str(e.value) for e in at.exception],
}
out["pass"]=out["inline_cards"]>1 and not out["open_visible"] and not out["back_visible"] and out["annotation_filter"] and out["summary"] and out["initial_resolver_calls"]==0 and out["one_documents_resolver_calls"]==1 and out["cards_remain"]==out["inline_cards"] and not out["exceptions"]
print(json.dumps(out, ensure_ascii=False, indent=2)); raise SystemExit(0 if out["pass"] else 1)
