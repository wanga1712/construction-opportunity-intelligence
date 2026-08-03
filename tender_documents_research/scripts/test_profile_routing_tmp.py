import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from document_processor.search_profile_config import load_search_profiles

cfg = load_search_profiles()
print(cfg.summary())

cases = [
    ("Ремонт улицы с наружным освещением и водоотводом", "road_infrastructure"),
    ("Капитальный ремонт здания школы", "social"),
    ("Устройство наливных полов в корпусе больницы", "social"),
    ("Ремонт моста и путепровода", "road_infrastructure"),
    ("Поставка офисной мебели", "social"),
]
for title, segment in cases:
    print("---", title)
    print(cfg.route_object(title=title, segment=segment, source="44fz"))
