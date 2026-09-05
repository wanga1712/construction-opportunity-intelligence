import hashlib
import os

files = [
    "src/ui/analytics_contour_v2_page.py",
    "src/ui/components/analytics_v2/stage_workspace.py",
    "src/ui/components/analytics_v2/card_feed.py",
    "src/ui/components/analytics_v2/annotation_card.py",
    "src/ui/components/analytics_v2/annotation_card_sections.py",
    "src/services/commercial_routing_v3/research_ui_projection.py"
]

def get_sha256_normalized(path):
    if not os.path.exists(path):
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        content = f.read()
        content_lf = content.replace(b"\r\n", b"\n")
        h.update(content_lf)
    return h.hexdigest()

print("--- HASHES ---")
for f in files:
    h = get_sha256_normalized(f)
    print(f"{f}:{h}")
