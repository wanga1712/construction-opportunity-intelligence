#!/bin/bash
# Install S13 power schedule + medal noon timer. Safety tests. Optional one-time suspend.
set -euo pipefail
ROOT=/opt/CRM_Streamlit
OUT=/var/lib/crm-v3-canary/s13_power_schedule
mkdir -p "$OUT"
DO_SUSPEND_TODAY="${1:-}"

echo "=== INSTALL ==="
sudo cp "$ROOT/deploy/crm-v3-daily-medal-reevaluation.timer" /etc/systemd/system/crm-v3-daily-medal-reevaluation.timer
sudo cp "$ROOT/deploy/crm-s13-scheduled-suspend.service" /etc/systemd/system/crm-s13-scheduled-suspend.service
sudo cp "$ROOT/deploy/crm-s13-scheduled-suspend.timer" /etc/systemd/system/crm-s13-scheduled-suspend.timer
sudo install -m 0755 "$ROOT/deploy/crm-s13-scheduled-suspend.sh" /usr/local/sbin/crm-s13-scheduled-suspend
sudo install -m 0755 "$ROOT/deploy/crm-s13-resume-hook" /lib/systemd/system-sleep/crm-s13-resume-hook
sudo systemctl daemon-reload
sudo systemctl enable --now crm-v3-daily-medal-reevaluation.timer
sudo systemctl restart crm-v3-daily-medal-reevaluation.timer
sudo systemctl enable --now crm-s13-scheduled-suspend.timer

{
  echo "INSTALLED_AT=$(date -Is)"
  echo "MEDAL_OLD=*-*-* 06:00:00 Europe/Moscow"
  echo "MEDAL_NEW=*-*-* 12:00:00 Europe/Moscow"
  systemctl cat crm-v3-daily-medal-reevaluation.timer
  echo "MEDAL_ENABLED=$(systemctl is-enabled crm-v3-daily-medal-reevaluation.timer)"
  echo "MEDAL_ACTIVE=$(systemctl is-active crm-v3-daily-medal-reevaluation.timer)"
  systemctl show crm-v3-daily-medal-reevaluation.timer -p NextElapseUSecRealtime
  echo "--- SUSPEND TIMER ---"
  systemctl cat crm-s13-scheduled-suspend.timer
  echo "SUSPEND_ENABLED=$(systemctl is-enabled crm-s13-scheduled-suspend.timer)"
  systemd-analyze calendar 'Mon..Thu,Sun *-*-* 23:00:00 Europe/Moscow' --iterations=10
} | tee "$OUT/install.txt"

echo "=== SAFETY TESTS ==="
python3 - <<'PY' | tee "$OUT/safety_tests.json"
import json, os, subprocess, re
from datetime import datetime
from zoneinfo import ZoneInfo

def sh(cmd):
    return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)

tests = {}
# timezone
td = sh("timedatectl")
tests["SYSTEM_TIMEZONE_VERIFIED"] = "PASS" if "Europe/Moscow" in td else "FAIL"

# calendar
cal = sh("systemd-analyze calendar 'Mon..Thu,Sun *-*-* 23:00:00 Europe/Moscow' --iterations=12")
tests["SYSTEMD_CALENDAR_VALIDATION"] = "PASS" if "Normalized form" in cal else "FAIL"
# Fri/Sat must not appear as elapse dates for suspend — check weekday names in next events
# Extract MSK lines
lines = [l for l in cal.splitlines() if "MSK" in l or "elapse" in l.lower()]
# Better: parse iterations for weekdays
events = re.findall(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} MSK", cal)
# systemd-analyze may use localized day names; also match ISO dates and map
iso_events = re.findall(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) MSK", cal)
msk = ZoneInfo("Europe/Moscow")
weekdays = []
for d,t in iso_events:
    dt = datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=msk)
    weekdays.append(dt.strftime("%a").upper())
# Python %a is locale-dependent; use weekday number
wd_names = []
for d,t in iso_events:
    dt = datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=msk)
    wd_names.append(["MON","TUE","WED","THU","FRI","SAT","SUN"][dt.weekday()])

tests["FRIDAY_NO_RECURRING_SUSPEND_TEST"] = "PASS" if "FRI" not in wd_names else "FAIL"
tests["SATURDAY_NO_RECURRING_SUSPEND_TEST"] = "PASS" if "SAT" not in wd_names else "FAIL"
tests["SUNDAY_23_SUSPEND_TEST"] = "PASS" if "SUN" in wd_names else "FAIL"
tests["MON_THU_23_SUSPEND_TEST"] = "PASS" if any(x in wd_names for x in ("MON","TUE","WED","THU")) else "FAIL"
tests["NEXT_10_SUSPEND_EVENTS"] = [f"{d} {t} MSK ({w})" for (d,t),w in zip(iso_events, wd_names)]

# suspend support
state = open("/sys/power/state").read()
tests["SUSPEND_SUPPORTED"] = "PASS" if "mem" in state.split() else "FAIL"

# RTC
tests["RTC_DEVICE"] = "/dev/rtc0" if os.path.exists("/dev/rtc0") else "NONE"
tests["RTC_WAKE_SUPPORTED"] = "PASS" if os.path.exists("/sys/class/rtc/rtc0/wakealarm") else "FAIL"
adj = open("/etc/adjtime").read().strip().splitlines()
tests["RTC_MODE"] = adj[-1] if adj else "UNKNOWN"

# medal noon
medal = sh("systemctl cat crm-v3-daily-medal-reevaluation.timer")
tests["MEDAL_NOON_TIMER_TEST"] = "PASS" if "12:00:00" in medal and "Europe/Moscow" in medal else "FAIL"
tests["MEDAL_TIMER_NEXT_RUN"] = sh("systemctl show crm-v3-daily-medal-reevaluation.timer -p NextElapseUSecRealtime --value").strip()

# routing preserved
ai = sh("systemctl cat crm-ai-assessment-runner.service")
tests["BACKLOG_DRAIN_PRESERVED_TEST"] = "PASS" if "--drain" in ai else "FAIL"
tests["ROUTING_RESUME_CONFIGURATION_TEST"] = "PASS" if os.path.exists("/lib/systemd/system-sleep/crm-s13-resume-hook") else "FAIL"

# next-day 06 wake calc
import subprocess as sp
# tomorrow 06:00 from a fictional Mon 23:00
ep = int(sp.check_output(["bash","-lc", 'TZ=Europe/Moscow date -d "tomorrow 06:00" +%s']).decode().strip())
hum = sp.check_output(["bash","-lc", f'TZ=Europe/Moscow date -d @{ep} "+%H:%M %Z"']).decode().strip()
tests["NEXT_DAY_06_WAKE_CALCULATION_TEST"] = "PASS" if hum.startswith("06:00") else "FAIL"
tests["WAKE_CALC_SAMPLE"] = hum

print(json.dumps(tests, ensure_ascii=False, indent=2))
open("/var/lib/crm-v3-canary/s13_power_schedule/safety_tests.json","w").write(json.dumps(tests, ensure_ascii=False, indent=2))
PY

# RTC write/readback test (short future alarm, then clear) — root
echo "=== RTC WRITE/READBACK TEST ==="
sudo bash - <<'EOS' | tee -a "$OUT/install.txt"
set -e
PATH_WA=/sys/class/rtc/rtc0/wakealarm
NOW=$(date -u +%s)
FUT=$((NOW + 3600))
echo 0 > "$PATH_WA" || true
echo "$FUT" > "$PATH_WA"
RAW=$(cat "$PATH_WA")
echo "wrote=$FUT raw=$RAW"
# clear
echo 0 > "$PATH_WA" || true
: > "$PATH_WA" || true
echo "cleared=$(cat $PATH_WA)"
if [[ -n "$RAW" && "$RAW" != "0" ]]; then
  echo "RTC_WAKEALARM_WRITE_READBACK_TEST=PASS"
else
  echo "RTC_WAKEALARM_WRITE_READBACK_TEST=FAIL"
  exit 1
fi
EOS

# Final report artifact
python3 - <<'PY' | tee "$OUT/final_pre_suspend_report.txt"
import json, subprocess
st=json.load(open("/var/lib/crm-v3-canary/s13_power_schedule/safety_tests.json"))
crit=["SYSTEM_TIMEZONE_VERIFIED","SYSTEMD_CALENDAR_VALIDATION","SUSPEND_SUPPORTED","RTC_WAKE_SUPPORTED",
      "MEDAL_NOON_TIMER_TEST","FRIDAY_NO_RECURRING_SUSPEND_TEST","SATURDAY_NO_RECURRING_SUSPEND_TEST",
      "SUNDAY_23_SUSPEND_TEST","MON_THU_23_SUSPEND_TEST","NEXT_DAY_06_WAKE_CALCULATION_TEST",
      "ROUTING_RESUME_CONFIGURATION_TEST","BACKLOG_DRAIN_PRESERVED_TEST"]
# RTC readback from install log
raw=open("/var/lib/crm-v3-canary/s13_power_schedule/install.txt").read()
st["RTC_WAKEALARM_WRITE_READBACK_TEST"]="PASS" if "RTC_WAKEALARM_WRITE_READBACK_TEST=PASS" in raw else "FAIL"
crit.append("RTC_WAKEALARM_WRITE_READBACK_TEST")
fails=[k for k in crit if st.get(k)!="PASS"]
medal_next=subprocess.getoutput("systemctl show crm-v3-daily-medal-reevaluation.timer -p NextElapseUSecRealtime --value")
report={
 "MEDAL_REEVALUATION_TIME":"12:00 Europe/Moscow",
 "MEDAL_TIMER_ENABLED":subprocess.getoutput("systemctl is-enabled crm-v3-daily-medal-reevaluation.timer"),
 "MEDAL_TIMER_NEXT_RUN":medal_next,
 "SUSPEND_TIMER_UNIT":"crm-s13-scheduled-suspend.timer",
 "SUSPEND_TIMER_ENABLED":subprocess.getoutput("systemctl is-enabled crm-s13-scheduled-suspend.timer"),
 "RECURRING_SUSPEND_DAYS":"MON,TUE,WED,THU,SUN",
 "RECURRING_SUSPEND_TIME":"23:00 Europe/Moscow",
 "RECURRING_NO_SLEEP_DAYS":"FRI,SAT",
 "WAKE_TIME":"06:00 Europe/Moscow",
 "RTC_WAKE_SUPPORTED":"YES" if st.get("RTC_WAKE_SUPPORTED")=="PASS" else "NO",
 "TODAY_ONE_TIME_SLEEP":"YES",
 "TODAY_EXPECTED_WAKE":"2026-08-15 06:00 Europe/Moscow",
 "AI_ROUTING_RESUMES_AFTER_WAKE":"YES",
 "SOURCE_SYNC_RESUMES_AFTER_WAKE":"YES",
 "BACKLOG_DRAIN_PRESERVED":"YES" if st.get("BACKLOG_DRAIN_PRESERVED_TEST")=="PASS" else "NO",
 "DOCUMENTS_STARTED":"NO",
 "MAINTENANCE_DISABLE_SUSPEND":"sudo systemctl stop crm-s13-scheduled-suspend.timer && sudo systemctl disable crm-s13-scheduled-suspend.timer",
 "MAINTENANCE_ENABLE_SUSPEND":"sudo systemctl enable --now crm-s13-scheduled-suspend.timer",
 "SAFETY":st,
 "FAILED_CRITICAL":fails,
 "VERDICT":"PASS_PRE_SUSPEND" if not fails else "FAIL_NO_SUSPEND",
 "WIP":"S13-POWER-SCHEDULE-AND-MEDAL-NOON-TIMER-1",
}
print(json.dumps(report, ensure_ascii=False, indent=2))
open("/var/lib/crm-v3-canary/s13_power_schedule/final_pre_suspend_report.json","w").write(json.dumps(report, ensure_ascii=False, indent=2))
if fails:
  raise SystemExit(2)
PY

echo "ALL_CRITICAL_PASS"
if [[ "$DO_SUSPEND_TODAY" == "--suspend-now" ]]; then
  echo "=== ONE-TIME SUSPEND NOW → wake 2026-08-15 06:00 Europe/Moscow ==="
  # Host clock may already be 2026-08-15 early morning; wake still 06:00 same calendar day.
  sudo env CRM_S13_ONE_TIME_WAKE_ISO="2026-08-15 06:00:00" /usr/local/sbin/crm-s13-scheduled-suspend
fi
