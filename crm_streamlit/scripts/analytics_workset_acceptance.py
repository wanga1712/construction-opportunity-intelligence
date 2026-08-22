#!/usr/bin/env python3
"""Read-only real-route acceptance for expert workset/card presentation."""
import json, os, re, sys
from pathlib import Path
root=Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit")); os.chdir(root); sys.path[:0]=[str(root), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]
from dotenv import load_dotenv
load_dotenv(root/".env", override=True)
from streamlit.testing.v1 import AppTest
from src.ui.components.analytics_v2 import annotation_card

calls=[]; real=annotation_card.load_annotation_card_view
def counted(*args, **kwargs): calls.append(args[0]); return real(*args, **kwargs)
annotation_card.load_annotation_card_view=counted
at=AppTest.from_file("app.py", default_timeout=240); at.session_state["nav_page"]="objects_v2"; at.run(timeout=240)
stage=next(r for r in at.radio if "Идут торги" in list(r.options)); stage.set_value("Идут торги"); at.run(timeout=240)
groups=list(at.get("button_group")); section_groups=[g for g in groups if g.label=="Раздел карточки"]
annotation_group=next(g for g in groups if g.label=="Экспертная разметка")
all_count=int(re.search(r"(\d+)$", str(annotation_group.options[0])).group(1))
initial=len(calls); before=len(section_groups)
document_option=next(value for value in section_groups[0].options if str(value).startswith("Документы"))
section_groups[0].set_value(document_option); at.run(timeout=240)
markdown="\n".join(str(x.value) for x in at.markdown)
captions="\n".join(str(x.value) for x in at.caption)
links=list(at.get("link_button")); hrefs=[getattr(x,"url",None) for x in links]
try: category_explicit=at.session_state["_catf_torgi_explicit"]
except KeyError: category_explicit="missing"
out={
 "category_explicit": category_explicit,
 "inline_cards": before, "annotation_options": list(annotation_group.options),
 "initial_resolver_calls": initial, "one_document_resolver_calls": len(calls)-initial,
 "cards_remain": len([g for g in at.get("button_group") if g.label=="Раздел карточки"]),
 "open_button": any(b.label=="Открыть карточку" for b in at.button),
 "back_button": any("Назад к списку" in b.label for b in at.button),
 "workset_total": all_count,
 "true_total_visible": f"Идут торги · {all_count}" in markdown,
 "page_range_visible": f"Показано 1–25 из {all_count}" in (markdown + captions),
 "icons_visible": all(icon in markdown for icon in ("💰","📅","📜","🏢","📍")),
 "technical_line_absent": "files/matches/evidence" not in markdown and "route:" not in markdown,
 "source_links": len([url for url in hrefs if url]),
 "exceptions": [str(e.value) for e in at.exception],
}
out["pass"]=all((all_count>20, before==25, not out["open_button"], not out["back_button"], out["true_total_visible"], out["page_range_visible"], out["icons_visible"], out["technical_line_absent"], initial==0, out["one_document_resolver_calls"]==1, out["cards_remain"]==25, out["source_links"]>0, not out["exceptions"]))
print(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit(0 if out["pass"] else 1)
