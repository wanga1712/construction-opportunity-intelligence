"""Central thresholds and paths for multi-host system health."""
from __future__ import annotations

from pathlib import Path

COLLECTOR_VERSION = "1.3.0"

DEFAULT_STATE_DIR = "/var/lib/crm-system-health"
LATEST_NAME = "latest.json"
HISTORY_DB_NAME = "history.sqlite3"

HOST_S13 = "S13"
HOST_S7 = "S7"
MONITORED_HOSTS = (HOST_S13, HOST_S7)
PAGE_LABEL = "Состояние серверов"

FAST_INTERVAL_SEC = 12
SMART_INTERVAL_SEC = 300
S7_INTERVAL_SEC = 30
HISTORY_AGG_INTERVAL_SEC = 60
HISTORY_RETENTION_HOURS = 24
UI_REFRESH_SEC = 8
STALE_AFTER_SEC = 45
COLLECTOR_DOWN_AFTER_SEC = 120
S7_STALE_AFTER_SEC = 90

# S7 remote (collector only — never from UI)
S7_SSH_TARGET = "<S7_SSH_USER>@S7"
S7_SSH_IDENTITY = "<HOME>/.ssh/id_to_nyx"
S7_CONNECT_TIMEOUT = 5
S7_COMMAND_TIMEOUT = 25
S7_COLLECTION_TIMEOUT = 60

# Filesystem
DISK_USED_WARN_PCT = 85.0
DISK_USED_CRIT_PCT = 95.0
INODE_USED_WARN_PCT = 90.0
INODE_USED_CRIT_PCT = 97.0

# Temperatures (°C) — central policy
CPU_TEMP_WARN_C = 70.0
CPU_TEMP_CRIT_C = 85.0
DISK_TEMP_WARN_C = 50.0
DISK_TEMP_CRIT_C = 60.0

# Sustained CPU (history-based)
SUSTAINED_CPU_WARN_PCT = 90.0
SUSTAINED_CPU_MIN_SAMPLES = 5  # ~5 minutes at 1-min history

# NVMe / wear
NVME_PCT_USED_WARN = 90
NVME_PCT_USED_CRIT = 100

IMPORTANT_MOUNTS_S13 = ("/", "/data")
IMPORTANT_MOUNTS_S7 = ("/",)

# Long-running expected-active on S13
SERVICE_EXPECTED_ACTIVE = (
    "crm-streamlit.service",
    "crm-system-health-collector.service",
    "crm-v3-analytics-refresh.timer",
    "postgresql.service",
)

# Timer-backed oneshot — idle/activating must NOT be CRITICAL
SERVICE_ONESHOT_TIMER = {
    "crm-procurement-sync.service": "crm-procurement-sync.timer",
}

SERVICE_EXPECTED_FROZEN = (
    "crm-ai-assessment-runner.timer",
    "crm-ai-assessment-runner.service",
    "tender-docs-daemon-open.service",
    "tender-docs-daemon-awarded.service",
)

SERVICE_WATCH_OPTIONAL = (
    "crm-computer-tz-loop.service",
    "ollama.service",
    "crm-v3-analytics-refresh.service",
)

S7_SOURCE_COLLECTORS = (
    "tendermonitor-eis-parser.service",
    "tendermonitor-eis-parser-backward.service",
    "tendermonitor-daily-migration.timer",
    "tendermonitor-monitoring.timer",
)

FAKE_DISK_HEALTH_PERCENT = False
EXPECTED_INACTIVE_IS_FAILURE = False
TRANSIENT_ONESHOT_RUNNING_IS_CRITICAL = False
SMART_OVERALL_PASS_HIDES_SECTOR_ERRORS = False
INVALID_CPU_SAMPLE_DISPLAYED_AS_ZERO = False
SYSTEM_HEALTH_MUTATING_ACTIONS = 0
UI_HARDWARE_PROBES = 0
HARDWARE_PROBES_ON_UI_RERUN = False
S7_SSH_CALLS_ON_UI_RERUN = 0
HEALTH_HISTORY_BOUNDED = True
HEALTH_HISTORY_MULTI_HOST = True
HISTORY_LOADED_ON_OVERVIEW = False
PARTIAL_SNAPSHOT_VISIBLE = False
LAST_GOOD_SURVIVES_FAILURE = True
S7_FAILURE_BREAKS_S13_MONITORING = False
S7_TEMP_FAKE_VALUE = False
SUSTAINED_CPU_ALERT = True
ZERO_SMART_ACCESS_NOT_EQUAL_ZERO_DISKS = True


def state_dir() -> Path:
    import os

    return Path(os.environ.get("CRM_SYSTEM_HEALTH_DIR", DEFAULT_STATE_DIR))


def latest_path(root: Path | None = None) -> Path:
    return (root or state_dir()) / LATEST_NAME


def history_db_path(root: Path | None = None) -> Path:
    return (root or state_dir()) / HISTORY_DB_NAME
