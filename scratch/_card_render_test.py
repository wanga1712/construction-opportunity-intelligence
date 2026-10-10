"""Headless-проверка рендера карточки прямой поставки (Streamlit AppTest)."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import streamlit as st
from streamlit.testing.v1 import AppTest

PID = int(os.getenv("CARD_PID", "459631"))


def _page() -> None:
    import os

    import streamlit as st

    from src.services.db_bootstrap import connect_databases
    from src.services.procurement_card_dossier_service import load_procurement_dossier
    from src.ui.procurement_card_page import _render_dossier

    pid = int(os.getenv("CARD_PID", "459631"))
    _radar, _tender, crm_db, _warn = connect_databases()
    dossier = load_procurement_dossier(crm_db, pid)
    _render_dossier(dossier, crm_db)


at = AppTest.from_function(_page, default_timeout=300)
at.run()
if at.exception:
    for exc in at.exception:
        print("EXCEPTION:", exc.value if hasattr(exc, "value") else exc)
    raise SystemExit(1)

print("tabs:")
for tab in at.tabs:
    print("   -", tab.label)
print("expanders:", len(at.expander))
print("buttons:", [b.label for b in at.button][:10])
print("markdown blocks:", len(at.markdown))
texts = "\n".join(str(m.value) for m in at.markdown)
for needle in ("Смета", "Товар и поставка", "Сервер вычислительный", "Процессор и вычисления",
               "Требования к поставке", "Обеспечение", "Срок поставки"):
    print("   содержит «%s»: %s" % (needle, needle in texts))
