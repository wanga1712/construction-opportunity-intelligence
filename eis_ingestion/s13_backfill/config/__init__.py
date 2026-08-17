from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw) if raw else default

CONFIG_INI_PATH = _path_from_env("TENDERMONITOR_CONFIG", BASE_DIR / "config.ini")
PROCESSED_DATES_FILE = _path_from_env(
    "TENDERMONITOR_PROCESSED_DATES", BASE_DIR / "processed_dates.json"
)
REGION_PROGRESS_FILE = _path_from_env(
    "TENDERMONITOR_REGION_PROGRESS", BASE_DIR / "region_progress.json"
)
