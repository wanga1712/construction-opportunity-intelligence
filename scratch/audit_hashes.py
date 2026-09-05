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

def get_sha256(path):
    if not os.path.exists(path):
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

print("--- HASHES ---")
for f in files:
    h = get_sha256(f)
    print(f"{f}:{h}")
