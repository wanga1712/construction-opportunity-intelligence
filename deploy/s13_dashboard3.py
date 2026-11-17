#!/usr/bin/env python3
# PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1
import json, os, re, socket, subprocess, sys, threading, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# System health probes — единый источник CPU/temp (read-only, без выдуманных нулей).
CRM_ROOT = "/opt/CRM_Streamlit"
if CRM_ROOT not in sys.path:
    sys.path.insert(0, CRM_ROOT)
KIOSK_SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
if KIOSK_SOURCE_DIR not in sys.path:
    sys.path.insert(0, KIOSK_SOURCE_DIR)
from s13_kiosk_truth import collect_today_truth

try:
    from src.services.match_source_filter import (
        NON_RESEARCHABLE_PATTERNS, RESEARCHABLE_PATTERNS,
    )
    from src.services.works_vs_goods_service import (
        NUMBER_PREFIX_REGEX_PATTERN, WORK_NAME_REGEX_PATTERN,
    )
except Exception:
    NON_RESEARCHABLE_PATTERNS = None
    RESEARCHABLE_PATTERNS = None
    NUMBER_PREFIX_REGEX_PATTERN = None
    WORK_NAME_REGEX_PATTERN = None

def sh(c,t=10):
    try: return subprocess.run(c,shell=True,capture_output=True,text=True,timeout=t).stdout.strip()
    except Exception: return ""
def pq(db,q,t=20):
    return sh("runuser -u postgres -- psql -d %s -At -F'|' -c \"%s\"" % (db,q),t)
def truth_pq(db,q,t=20):
    readonly_sql="BEGIN READ ONLY;\n%s;\nCOMMIT;" % q.rstrip().rstrip(";")
    proc=subprocess.run(["runuser","-u","postgres","--","psql","-X","-q","-A","-t","-F","|","-d",db,"-v","ON_ERROR_STOP=1","-c",readonly_sql],capture_output=True,text=True,timeout=t)
    if proc.returncode:
        raise RuntimeError("read-only kiosk truth query failed (%s): %s"%(db,(proc.stderr or "").strip()[:180]))
    return proc.stdout
def svc(n): return subprocess.run(["systemctl","is-active",n],capture_output=True,text=True).stdout.strip() or "?"
def svc_label(state):
    return {"active":"РАБОТАЕТ","activating":"ЗАПУСКАЕТСЯ",
            "reloading":"ПЕРЕЗАПУСК","inactive":"ОСТАНОВЛЕН",
            "failed":"ОШИБКА"}.get(str(state or "").strip(),"НЕИЗВЕСТНО")
def rows(out):
    r=[]
    for l in out.splitlines():
        if "|" in l: r.append(l.split("|"))
    return r

def current_research_authority_ids():
    """Snapshot the same CURRENT category-opportunity set used by consumers."""
    sql = """SELECT DISTINCT procurement_id
      FROM crm_procurement_category_opportunities
     WHERE status='CURRENT'
       AND research_action IN ('LIGHT_RESEARCH','PRIORITY_DOCS','DEEP_RESEARCH')
       AND upper(coalesce(nullif(current_effective_medal,''),candidate_medal,'')) IN ('GOLD','SILVER')
       AND upper(coalesce(opportunity_track,'')) NOT IN ('','UNKNOWN','NO_COMMERCIAL_ENTRY')
       AND upper(coalesce(commercial_state,'')) NOT IN
           ('NO_COMMERCIAL_ENTRY','CLOSED','CLOSED_DIRECT_SUPPLY',
            'COMMERCIAL_WINDOW_CLOSED','WAITING_SOURCE_OUTCOME','SUPPRESSED')"""
    output = pq("crm", sql, 30)
    return sorted({int(line.strip()) for line in output.splitlines() if line.strip().isdigit()})
def i(x):
    try: return int(str(x).strip())
    except Exception: return None
def f(x):
    try: return float(str(x).strip())
    except Exception: return None
def fs(path):
    try:
        with open(path) as fh: return fh.read().strip()
    except Exception: return ""

ROUTING_STATUS_PATH="/var/lib/crm-v3-canary/continuous_backlog_drain/routing_status.json"

def routing_backlog_count():
    try:
        with open(ROUTING_STATUS_PATH) as fh:
            payload=json.load(fh)
        # During drain, TOTAL_ELIGIBLE_BACKLOG is only the live batch lanes.
        # The selector also reports review/discovery candidates separately.
        backlog=payload.get("backlog") or {}
        # New backlog contract already includes discovery in TOTAL_ROUTING_ELIGIBLE_BACKLOG.
        full=backlog.get("TOTAL_ROUTING_ELIGIBLE_BACKLOG")
        if full is not None:
            return int(full or 0)
        # Backward-compatible fallback for older status payloads.
        live=payload.get("TOTAL_ELIGIBLE_BACKLOG")
        discovery=backlog.get("OTHER_SELECTABLE_LANES")
        if backlog and (live is not None or discovery is not None):
            return int(live or 0) + int(discovery or 0)
        # A completed canonical selector may persist its full selected count.
        if payload.get("queue_count_selected") is not None:
            value=payload.get("TOTAL_ELIGIBLE_BACKLOG")
            return int(value) if value is not None else None
        return None
    except Exception:
        return None

def cpu_cap_detail():
    base="/sys/devices/system/cpu"
    cur=fs(base+"/cpu0/cpufreq/scaling_cur_freq")
    smax=fs(base+"/cpu0/cpufreq/scaling_max_freq")
    hmax=fs(base+"/cpu0/cpufreq/cpuinfo_max_freq")
    max_pct=fs(base+"/intel_pstate/max_perf_pct")
    min_pct=fs(base+"/intel_pstate/min_perf_pct")
    no_turbo=fs(base+"/intel_pstate/no_turbo")
    governor=fs(base+"/cpu0/cpufreq/scaling_governor")
    mhz=lambda v: round(float(v)/1000.0,2) if v and v.isdigit() else None
    return {"cap_pct":i(max_pct),"min_pct":i(min_pct),
            "no_turbo":(i(no_turbo)==1) if no_turbo.isdigit() else None,
            "governor":governor or None,
            "cur_mhz":mhz(cur),"scaling_max_mhz":mhz(smax),"hw_max_mhz":mhz(hmax)}

def mem():
    d={}
    for l in open("/proc/meminfo"):
        k,v=l.split(":",1); d[k]=int(v.split()[0])
    tot=d["MemTotal"]/1048576; av=d["MemAvailable"]/1048576; st=d.get("SwapTotal",0)/1048576; sf=d.get("SwapFree",0)/1048576
    return {"pct":int((tot-av)/tot*100) if tot else 0,"used":round(tot-av,1),"total":round(tot,1),"swap":round(st-sf,1)}
def gpu():
    fields=("utilization.gpu,memory.used,memory.total,power.draw,power.limit,"
            "power.default_limit,power.max_limit,temperature.gpu,fan.speed,"
            "clocks.current.graphics,clocks.max.graphics,clocks.current.memory,"
            "clocks.max.memory,clocks_throttle_reasons.active")
    o=sh("nvidia-smi --query-gpu="+fields+" --format=csv,noheader,nounits 2>/dev/null")
    if not o: return None
    try:
        p=[x.strip() for x in o.split(",")]
        if len(p)<14: return None
        n=lambda x:f(None if x in ("[N/A]","[Not Supported]") else x)
        u,mu,mt,pw,pl,dl,ml,gt,fn,cc,mc,cm,mm=p[:13]; throttle=p[13]
        util=n(u); used=n(mu); totalm=n(mt); power=n(pw); limit=n(pl)
        default=n(dl); maxlimit=n(ml); temp=n(gt); fan=n(fn)
        try: reason_bits=int(throttle,16) if throttle.startswith("0x") else 0
        except Exception: reason_bits=None
        reasons=[]
        if reason_bits is not None:
            for bit,label in ((0x2,"APPLICATIONS_CLOCKS"),(0x4,"SW_POWER_CAP"),
                              (0x8,"HW_SLOWDOWN"),(0x10,"HW_THERMAL_SLOWDOWN"),
                              (0x20,"HW_POWER_BRAKE"),(0x80,"SYNC_BOOST")):
                if reason_bits & bit: reasons.append(label)
        cap_pct=round(limit/default*100,1) if limit and default else None
        draw_ratio=(power/limit) if power is not None and limit else None
        if any(x in reasons for x in ("SW_POWER_CAP","HW_POWER_BRAKE")):
            state="POWER_LIMIT"
        elif draw_ratio is not None and draw_ratio>=0.95:
            state="NEAR_POWER_CAP"
        else: state="NOT_POWER_LIMITED"
        return {"util":round(util,1) if util is not None else None,
                "vram_used":round(used) if used is not None else None,
                "vram_total":round(totalm) if totalm is not None else None,
                "pct":round(used/totalm*100,1) if used is not None and totalm else None,
                "power":round(power,1) if power is not None else None,
                "limit":round(limit,1) if limit is not None else None,
                "default_limit":round(default,1) if default is not None else None,
                "max_limit":round(maxlimit,1) if maxlimit is not None else None,
                "power_cap_pct":cap_pct,
                "headroom_w":round(limit-power,1) if limit is not None and power is not None else None,
                "locked_w":round(default-limit,1) if default is not None and limit is not None else None,
                "temp":round(temp) if temp is not None else None,
                "fan":round(fan) if fan is not None else None,
                "clock_cur_mhz":round(n(cc)) if n(cc) is not None else None,
                "clock_max_mhz":round(n(mc)) if n(mc) is not None else None,
                "mem_clock_cur_mhz":round(n(cm)) if n(cm) is not None else None,
                "mem_clock_max_mhz":round(n(mm)) if n(mm) is not None else None,
                "throttle_reasons":reasons,"throttle_bits":throttle,"power_state":state}
    except Exception: return None
def cpu_metrics():
    """CPU total + per-core из system_health_probes; без валидного сэмпла — None."""
    try:
        from src.services.system_health_probes import collect_cpu
        c = collect_cpu()
        per = c.get("per_core_pct") or []
        total = c.get("usage_pct")
        cap=cpu_cap_detail(); busy=total
        return {
            "total": total,
            "busy_pct": busy,
            "status": c.get("usage_pct_status"),
            "cores": c.get("cores"),
            "per": per,
            "min": min(per) if per else None,
            "max": max(per) if per else None,
            "model": c.get("model"),
            "freq_mhz": cap.get("cur_mhz") or c.get("freq_mhz"),
            "cap": cap,
            "approx_hw_pct": round(float(busy)*float(cap["cap_pct"])/100.0,1)
                if busy is not None and cap.get("cap_pct") is not None else None,
            "free_inside_cap_pct": round(100.0-float(busy),1) if busy is not None else None,
            "limited_by_cap_pct": round(100.0-float(cap["cap_pct"]),1)
                if cap.get("cap_pct") is not None else None,
        }
    except Exception:
        return {"total": None, "status": "NOT_AVAILABLE", "cores": None,
                "per": [], "min": None, "max": None, "model": None, "freq_mhz": None,
                "busy_pct":None,"cap":{},"approx_hw_pct":None,
                "free_inside_cap_pct":None,"limited_by_cap_pct":None}

def temperatures():
    """Package/max-core temp + источник + WARN/CRIT статус. Нет датчика -> None."""
    try:
        from src.services.system_health_temps import collect_local_temperature_bundle
        b = collect_local_temperature_bundle()
        return {
            "package": b.get("cpu_package_temp_c"),
            "core_max": b.get("cpu_core_max_temp_c"),
            "display": b.get("display_cpu_temp_c"),
            "status": b.get("display_cpu_temp_status") or "UNKNOWN",
            "source": b.get("cpu_temp_source"),
        }
    except Exception:
        return {"package": None, "core_max": None, "display": None,
                "status": "UNKNOWN", "source": None}
def cooling():
    o=sh("sensors 2>/dev/null"); f=[]
    for fid,rpm in re.findall(r"fan(\d+):\s+(\d+) RPM",o):
        if int(rpm)>0: f.append({"rpm":int(rpm)})
    return {"fans":f}
def disks():
    res=[]
    for dev,mnt in (("sda","/"),("sdc","/data")):
        d={"dev":dev,"mount":mnt}
        o=sh("df -h "+mnt+" 2>/dev/null | awk 'NR==2{gsub(\"%\",\"\",$5);print $5}'")
        d["pct"]=i(o)
        sm=sh("smartctl -H -A /dev/"+dev+" 2>/dev/null")
        d["health"]="PASSED" if "PASSED" in sm else "?"
        m=re.search(r"Temperature_Celsius.*?-\s*(\d+)",sm); d["temp"]=int(m.group(1)) if m else None
        res.append(d)
    return res

CACHE={"data":{},"ts":0}
RUNTIME={"data":{},"ts":0}
CONTOUR_CACHE={"data":None,"ts":0}
NORMALIZATION_CACHE={"data":None,"ts":0}
TODAY_TRUTH_CACHE={"data":None,"ts":0}
API_CACHE={"data":None,"ts":0}
API_CACHE_LOCK=threading.Lock()
RATE_WINDOW_MIN=60
ETA_OK_MAX_HOURS=12
ETA_EDGE_MAX_HOURS=24
ADMISSION_POLICY="BUSINESS_RESEARCH_ADMISSION_V2"
MAX_ROUTING_ATTEMPTS=int(os.environ.get("CRM_V3_ROUTING_MAX_ATTEMPTS","3"))
DAY_START_MAX_AGE_SECONDS=36*60*60

def parse_gpu_compute_apps(output, by_pid, unit_lookup):
    result=[]
    for line in output.splitlines():
        p=[x.strip() for x in line.split(",",2)]
        if len(p)==3 and p[0].isdigit():
            pid=int(p[0]); owner=by_pid.get(pid,{})
            result.append({"pid":pid,"process":p[1],"memory":p[2],"unit":unit_lookup(pid),"parent":by_pid.get(owner.get("ppid"),{}).get("cmd")})
    return result

def parse_current_assessment(lines):
    current=None
    for line in lines:
        m=re.search(r"Processing CRM ID (\d+)",line)
        if m: current=int(m.group(1))
        if current and re.search(r"persisted .*procurement_id=%d"%current,line): current=None
    return current

def document_runtime_counts(ready, processing, active_workers):
    return {"ready":ready,"processing":processing,"stale":processing if not active_workers else 0,
            "state":"STALE_PROCESSING" if processing and not active_workers else ("RUNNING" if processing else ("READY" if ready else "IDLE"))}

def classify_service_runtime(active_state, main_pid, has_work):
    if active_state=="failed": return "FAILED"
    if active_state!="active" or not main_pid: return "STOPPED"
    return "RUNNING" if has_work else "IDLE"

def normalization_runtime_state(implemented, running):
    return "RUNNING" if running else ("OFF" if implemented else "NOT_FOUND")

def parse_runtime_events(lines, limit=20):
    result=[]
    for line in lines[-limit:]:
        idm=re.search(r"(?:CRM ID|procurement_id=)(\d+)",line)
        result.append({"time":line[:25],"stage":"assessment" if "assessment" in line.lower() else ("feeder" if "feeder" in line.lower() else "documents"),"event":line[-180:],"procurement":idm.group(1) if idm else "—"})
    return result

def daily_kpis():
    """Bounded daily funnel/awards + real rolling throughput."""
    out={"available":True,"rate_window_min":RATE_WINDOW_MIN,
         "eta_ok_max_hours":ETA_OK_MAX_HOURS,"eta_edge_max_hours":ETA_EDGE_MAX_HOURS,
         "today":{"received":None,"direct":None,"object":None,"unknown":None,"processed":None},
         "yesterday":{"received":None,"direct":None,"object":None,"unknown":None,"processed":None},
         "speed_per_hour":None,"awarded_today":{"direct":0,"object":0,"other":0}}
    try:
        receive_sql=("""
        WITH pids AS (
          SELECT p.id,p.crm_created_at,
                 coalesce(bool_or(o.opportunity_track='DIRECT_SUPPLY'),false) AS is_direct,
                 coalesce(bool_or(o.opportunity_track IN
                   ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT','DESIGN_INFLUENCE')),false) AS is_object
            FROM crm_procurements p
            LEFT JOIN crm_procurement_category_opportunities o
              ON o.procurement_id=p.id AND o.status='CURRENT'
           WHERE p.crm_created_at >= current_date-interval '1 day'
             AND p.crm_created_at < current_date+interval '1 day'
           GROUP BY p.id,p.crm_created_at
        )
        SELECT CASE WHEN crm_created_at>=current_date THEN 'today' ELSE 'yesterday' END,
               count(*),
               count(*) FILTER (WHERE is_direct),
               count(*) FILTER (WHERE NOT is_direct AND is_object),
               count(*) FILTER (WHERE NOT is_direct AND NOT is_object)
          FROM pids GROUP BY 1
        """)
        for r in rows(pq("crm",receive_sql,20)):
            day=r[0] if r[0] in ("today","yesterday") else None
            if day:
                out[day].update({"received":i(r[1]),"direct":i(r[2]),
                                 "object":i(r[3]),"unknown":i(r[4])})
        current_ids = current_research_authority_ids()
        current_array = "ARRAY[" + ",".join(str(pid) for pid in current_ids) + "]::bigint[]"
        qsql=f"""
        SELECT count(DISTINCT procurement_id) FILTER (WHERE completed_at>=current_date),
               count(DISTINCT procurement_id) FILTER
                 (WHERE completed_at>=current_date-interval '1 day' AND completed_at<current_date),
               count(DISTINCT procurement_id) FILTER
                 (WHERE completed_at>=now()-interval '60 minutes')
          FROM document_processing_queue
         WHERE status='COMPLETED' AND pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
           AND procurement_id=ANY({current_array})
           AND category_context->>'commercial_authority_version'='CURRENT_CATEGORY_OPPORTUNITY_V1'
           AND category_context->>'current_research_eligible'='true'
        """
        qr=rows(pq("document_intelligence",qsql,20))
        if qr:
            out["today"]["processed"]=i(qr[0][0])
            out["yesterday"]["processed"]=i(qr[0][1])
            completed_last=float(i(qr[0][2]) or 0)
            out["speed_per_hour"]=round(completed_last*60.0/RATE_WINDOW_MIN,2)
        award_sql=("""
        WITH pids AS (
          SELECT p.id,
                 coalesce(bool_or(o.opportunity_track='DIRECT_SUPPLY'),false) AS is_direct,
                 coalesce(bool_or(o.opportunity_track IN
                   ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT','DESIGN_INFLUENCE')),false) AS is_object
            FROM crm_procurements p
            LEFT JOIN crm_procurement_category_opportunities o
              ON o.procurement_id=p.id AND o.status='CURRENT'
           WHERE p.award_date=current_date
           GROUP BY p.id
        )
        SELECT count(*) FILTER (WHERE is_direct),
               count(*) FILTER (WHERE NOT is_direct AND is_object),
               count(*) FILTER (WHERE NOT is_direct AND NOT is_object)
          FROM pids
        """)
        ar=rows(pq("crm",award_sql,20))
        if ar:
            out["awarded_today"]={"direct":i(ar[0][0]) or 0,
                                  "object":i(ar[0][1]) or 0,
                                  "other":i(ar[0][2]) or 0}
    except Exception as e:
        out["available"]=False
        out["error"]=str(e)
    return out

def _rate_from_last_jobs(times):
    ts=[]
    for x in times:
        try:
            import datetime as _dt
            ts.append(_dt.datetime.fromisoformat(x.replace("+00","+00:00")))
        except Exception:
            pass
    if len(ts)<2:
        return None
    span=(max(ts)-min(ts)).total_seconds()
    return round((len(ts)-1)*3600.0/span,2) if span>0 else None

MODEL_COMMERCIAL_STATES=("ACTIVE","FOLLOW_UP_AWARDED")

def _sql_like_array(patterns):
    values=[]
    for pattern in patterns or ():
        escaped=str(pattern).replace("'","''")
        values.append("'%"+escaped+"%'")
    return "ARRAY["+",".join(values)+"]::text[]"

def _model_source_filter(name_expr):
    if RESEARCHABLE_PATTERNS is None or NON_RESEARCHABLE_PATTERNS is None:
        raise RuntimeError("match_source_filter_unavailable")
    return ("lower("+name_expr+") LIKE ANY("+_sql_like_array(RESEARCHABLE_PATTERNS)+") "
            "AND lower("+name_expr+") NOT LIKE ALL("+
            _sql_like_array(NON_RESEARCHABLE_PATTERNS)+")")

def _model_goods_filter(name_expr):
    if WORK_NAME_REGEX_PATTERN is None or NUMBER_PREFIX_REGEX_PATTERN is None:
        raise RuntimeError("works_vs_goods_service_unavailable")
    number_pattern=NUMBER_PREFIX_REGEX_PATTERN.replace("'","''")
    work_pattern=WORK_NAME_REGEX_PATTERN.replace("'","''")
    return ("regexp_replace(coalesce("+name_expr+",''),'"+number_pattern+
            "','') !~* '"+work_pattern+"'")

def _pair_set(out):
    pairs=set()
    for r in rows(out):
        if len(r)>=2:
            pid=i(r[0]); category=(r[1] or "").strip()
            if pid is not None and category:
                pairs.add((pid,category))
    return pairs

def model_candidate_pool_metrics():
    out={"unit":"PROCUREMENT_X_CATEGORY","waiting":None,"working":None,
         "raw_waiting_rows":None,"raw_working_rows":None,
         "done_today":None,"raw_done_today":None,
         "confirmed_today":None,"rejected_today":None,"unknown_today":None,
         "throughput_per_hour":None,"current_opportunity_pairs":None,
         "source_filter":"RESEARCHABLE","goods_only":True,
         "commercial_states":list(MODEL_COMMERCIAL_STATES)}
    states_sql=",".join("'"+s.replace("'","''")+"'" for s in MODEL_COMMERCIAL_STATES)
    current_sql=f"""
        SELECT DISTINCT procurement_id,commercial_category_code
          FROM crm_procurement_category_opportunities
         WHERE status='CURRENT' AND commercial_state IN ({states_sql})
    """
    current_pairs=_pair_set(pq("crm",current_sql,30))
    out["current_opportunity_pairs"]=len(current_pairs)
    if not current_pairs:
        return out

    structured_source=_model_source_filter("f.file_name")
    structured_goods=_model_goods_filter("se.product_name_raw")
    waiting_sql=f"""
        SELECT DISTINCT se.procurement_id,se.category_code
          FROM structured_entities se
          JOIN document_files f ON f.id=se.source_document_id
         WHERE {structured_source}
           AND upper(coalesce(se.entity_type,''))<>'WORK'
           AND {structured_goods}
    """
    waiting_pairs=current_pairs & _pair_set(
        pq("document_intelligence",waiting_sql,40))
    out["waiting"]=len(waiting_pairs)

    raw_source=_model_source_filter(
        "coalesce(f.file_name,m.document_name,m.archive_member_path,'')")
    raw_goods=_model_goods_filter(
        "coalesce(d.matched_term,d.matched_text,'')")
    working_sql=f"""
        SELECT DISTINCT d.procurement_id,d.category_code
          FROM document_match_details d
          JOIN document_matches m ON m.id=d.match_id
          LEFT JOIN document_files f ON f.id=m.file_id
         WHERE d.validated_at IS NULL
           AND upper(coalesce(d.validation_status,'')) IN
               ('CLAIMED','PROCESSING','RUNNING','IN_PROGRESS')
           AND {raw_source}
           AND {raw_goods}
    """
    working_pairs=current_pairs & _pair_set(
        pq("document_intelligence",working_sql,40))
    out["working"]=len(working_pairs)

    validated_sql=f"""
        SELECT d.procurement_id,d.category_code,
               bool_or(upper(coalesce(d.validation_status,''))='CONFIRMED') AS confirmed,
               bool_or(upper(coalesce(d.validation_status,''))='REJECTED') AS rejected
          FROM document_match_details d
          JOIN document_matches m ON m.id=d.match_id
          LEFT JOIN document_files f ON f.id=m.file_id
         WHERE d.validated_at>=current_date
           AND {raw_source}
           AND {raw_goods}
         GROUP BY d.procurement_id,d.category_code
    """
    done=confirmed=rejected=unknown=0
    for r in rows(pq("document_intelligence",validated_sql,40)):
        if len(r)<4:
            continue
        pid=i(r[0]); category=(r[1] or "").strip()
        if (pid,category) not in current_pairs:
            continue
        done+=1
        if r[2]=="t":
            confirmed+=1
        elif r[3]=="t":
            rejected+=1
        else:
            unknown+=1
    out.update({"done_today":done,"confirmed_today":confirmed,
                "rejected_today":rejected,"unknown_today":unknown})

    raw_count_sql="""
        SELECT count(*) FILTER (
                 WHERE validated_at IS NULL
                   AND upper(coalesce(validation_status,'UNKNOWN'))
                       IN ('UNKNOWN','RAW','PENDING')),
               count(*) FILTER (
                 WHERE validated_at IS NULL
                   AND upper(coalesce(validation_status,''))
                       IN ('CLAIMED','PROCESSING','RUNNING','IN_PROGRESS')),
               count(*) FILTER (WHERE validated_at>=current_date)
          FROM document_match_details
    """
    rr=rows(pq("document_intelligence",raw_count_sql,40))
    if rr:
        out.update({"raw_waiting_rows":i(rr[0][0]),
                    "raw_working_rows":i(rr[0][1]),
                    "raw_done_today":i(rr[0][2])})
    sent_sql="""
        SELECT count(*)
          FROM document_matches m
          JOIN document_match_details d ON d.match_id = m.id
         WHERE m.created_at >= current_date
    """
    sr=i(pq("document_intelligence",sent_sql,40))
    if sr is not None:
        out["sent_today"]=sr

    val_job_sql=f"""
        WITH recent AS (
          SELECT d.procurement_id,d.category_code,d.validated_at
            FROM document_match_details d
            JOIN document_matches m ON m.id=d.match_id
            LEFT JOIN document_files f ON f.id=m.file_id
           WHERE d.validated_at>=now()-interval '7 days'
             AND {raw_source}
             AND {raw_goods}
           ORDER BY d.validated_at DESC LIMIT 5000
        ), pairs AS (
          SELECT procurement_id,category_code,max(validated_at) AS validated_at
            FROM recent GROUP BY procurement_id,category_code
           ORDER BY validated_at DESC LIMIT 30
        )
        SELECT procurement_id,category_code,validated_at
          FROM pairs ORDER BY validated_at
    """
    vj=[]
    for r in rows(pq("document_intelligence",val_job_sql,40)):
        if len(r)>=3:
            pid=i(r[0]); category=(r[1] or "").strip()
            if (pid,category) in current_pairs:
                vj.append(r[2])
    out["throughput_per_hour"]=_rate_from_last_jobs(vj)
    return out

def command_center_metrics():
    """Operator-level procurement funnel, document/model flow and commercial output."""
    out={"available":True,
         "today":{},"yesterday":{},"delta":{},
         "documents":{"waiting":None,"working":None,"done_today":None,
                      "parsed_today":None,
                      "errors":None,"no_links":None,"throughput_per_hour":None},
         "model":{"unit":"PROCUREMENT_X_CATEGORY","waiting":None,"working":None,
                  "raw_waiting_rows":None,"raw_working_rows":None,
                  "done_today":None,"raw_done_today":None,"sent_today":None,
                  "confirmed_today":None,"rejected_today":None,"unknown_today":None,
                  "throughput_per_hour":None},
         "commercial":{"objects":None,"with_commerce":None,"document_confirmed":None,
                       "category_opportunities":None,"result_today":None,
                       "result_yesterday":None,"open":{},"awarded":{}},
         "rates":{"arrivals_per_hour":None,"processed_per_hour":None},
         "rolling_5d":{"available":False,"window_days":5,"arrivals":None,
                       "processed":None,"avg_arrivals_per_day":None,
                       "avg_processed_per_day":None,"coverage_pct":None,
                       "balance_pct":None,"state":"UNKNOWN",
                       "arrival_days":0,"processed_days":0,
                       "warming_up":True}}
    try:
        funnel_sql=f"""
        WITH pids AS (
          SELECT p.id,p.crm_created_at,
                 coalesce(bool_or(a.admission_state='ELIGIBLE'
                   AND a.admission_policy_version='{ADMISSION_POLICY}'),false) AS admitted,
                 coalesce(bool_or(o.opportunity_track='DIRECT_SUPPLY'),false) AS is_direct,
                 coalesce(bool_or(o.opportunity_track IN
                   ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT','DESIGN_INFLUENCE')),false) AS is_object
            FROM crm_procurements p
            LEFT JOIN crm_procurement_scope_authority a ON a.procurement_id=p.id
            LEFT JOIN crm_procurement_category_opportunities o
              ON o.procurement_id=p.id AND o.status='CURRENT'
           WHERE p.crm_created_at >= current_date-interval '1 day'
             AND p.crm_created_at < current_date+interval '1 day'
           GROUP BY p.id,p.crm_created_at
        )
        SELECT CASE WHEN crm_created_at>=current_date THEN 'today' ELSE 'yesterday' END,
               count(*),count(*) FILTER (WHERE admitted),
               count(*) FILTER (WHERE is_direct),
               count(*) FILTER (WHERE NOT is_direct AND is_object),
               count(*) FILTER (WHERE NOT is_direct AND NOT is_object)
          FROM pids GROUP BY 1
        """
        for r in rows(pq("crm",funnel_sql,30)):
            day=r[0] if r[0] in ("today","yesterday") else None
            if day:
                out[day].update({"received":i(r[1]),"admitted":i(r[2]),
                                 "direct":i(r[3]),"object":i(r[4]),"unknown":i(r[5])})
        model_day_sql="""
        SELECT count(DISTINCT id) FILTER (WHERE ai_assessed_at>=current_date),
               count(DISTINCT id) FILTER
                 (WHERE ai_assessed_at>=current_date-interval '1 day'
                    AND ai_assessed_at<current_date)
          FROM crm_procurements
        """
        md=rows(pq("crm",model_day_sql,30))
        if md:
            out["today"]["model_processed"]=i(md[0][0])
            out["yesterday"]["model_processed"]=i(md[0][1])
        daily_process_sql=f"""
        SELECT count(DISTINCT cp.id) FILTER (
                 WHERE cp.ai_assessed_at>=current_date
                   AND (upper(coalesce(cp.ai_assessment_status,'')) IN
                          ('COMPLETED','NEEDS_REVIEW')
                        OR (upper(coalesce(cp.ai_assessment_status,''))='FAILED'
                            AND coalesce(cp.ai_routing_attempt_count,0)>={MAX_ROUTING_ATTEMPTS}))),
               count(DISTINCT cp.id) FILTER (
                 WHERE cp.ai_assessed_at>=current_date-interval '1 day'
                   AND cp.ai_assessed_at<current_date
                   AND (upper(coalesce(cp.ai_assessment_status,'')) IN
                          ('COMPLETED','NEEDS_REVIEW')
                        OR (upper(coalesce(cp.ai_assessment_status,''))='FAILED'
                            AND coalesce(cp.ai_routing_attempt_count,0)>={MAX_ROUTING_ATTEMPTS})))
          FROM crm_procurements cp
          JOIN crm_procurement_scope_authority a ON a.procurement_id=cp.id
         WHERE a.admission_state='ELIGIBLE'
           AND a.admission_policy_version='{ADMISSION_POLICY}'
           AND cp.ai_assessed_at>=current_date-interval '1 day'
        """
        dp=rows(pq("crm",daily_process_sql,30))
        if dp:
            out["today"]["processed"]=i(dp[0][0])
            out["yesterday"]["processed"]=i(dp[0][1])
        cohort_sql=f"""
        WITH recv AS (
          SELECT p.id,p.okpd_code,p.ai_assessed_at,p.ai_assessment_status,
                 EXISTS (
                   SELECT 1 FROM crm_procurement_scope_authority a
                    WHERE a.procurement_id=p.id
                      AND a.admission_state='ELIGIBLE'
                      AND a.admission_policy_version='{ADMISSION_POLICY}'
                 ) AS admitted,
                 EXISTS (
                   SELECT 1 FROM crm_procurement_category_opportunities o
                    WHERE o.procurement_id=p.id AND o.status='CURRENT'
                 ) AS has_current,
                 EXISTS (
                   SELECT 1 FROM crm_category_okpd_priors op
                    WHERE op.active
                      AND regexp_replace(coalesce(p.okpd_code,''),'[[:space:]]+','','g') <> ''
                      AND (
                        (upper(coalesce(op.match_type,'PREFIX'))='EXACT'
                         AND regexp_replace(coalesce(p.okpd_code,''),'[[:space:]]+','','g')
                             =regexp_replace(op.okpd_pattern,'[[:space:]]+','','g'))
                        OR
                        (upper(coalesce(op.match_type,'PREFIX')) IN ('PREFIX','BRANCH')
                         AND (
                           regexp_replace(coalesce(p.okpd_code,''),'[[:space:]]+','','g')
                             =regexp_replace(op.okpd_pattern,'[[:space:]]+','','g')
                           OR regexp_replace(coalesce(p.okpd_code,''),'[[:space:]]+','','g')
                             LIKE regexp_replace(op.okpd_pattern,'[[:space:]]+','','g') || '.%'
                         ))
                      )
                 ) AS has_prior
            FROM crm_procurements p
           WHERE p.crm_created_at>=current_date
        ), signals AS (
          SELECT *,
                 admitted AND (
                   has_prior OR has_current
                   OR COALESCE(ai_assessed_at>=current_date,false)
                 ) AS with_initial_signal,
                 admitted AND NOT (
                   has_prior OR has_current
                   OR COALESCE(ai_assessed_at>=current_date,false)
                 ) AS without_initial_signal
            FROM recv
        )
        SELECT count(*),
               count(*) FILTER (WHERE admitted),
               count(*) FILTER (WHERE with_initial_signal),
               count(*) FILTER (WHERE without_initial_signal),
               count(*) FILTER (
                 WHERE admitted AND ai_assessed_at>=current_date
               ),
               count(*) FILTER (
                 WHERE admitted
                   AND COALESCE(ai_assessed_at>=current_date,false)=false
                   AND upper(coalesce(ai_assessment_status,'')) IN
                       ('RUNNING','QUEUED')
               )
          FROM signals
        """
        cohort=rows(pq("crm",cohort_sql,30))
        if cohort:
            out["today"]["received"]=i(cohort[0][0])
            out["today"]["researchable_from_received"]=i(cohort[0][1])
            out["today"]["with_initial_signal"]=i(cohort[0][2])
            out["today"]["without_initial_signal"]=i(cohort[0][3])
            out["today"]["processed_from_received"]=i(cohort[0][4])
            out["today"]["in_progress_from_received"]=i(cohort[0][5])
        cohort_state_sql=f"""
        SELECT p.id,
               EXISTS (
                 SELECT 1 FROM crm_procurement_scope_authority a
                  WHERE a.procurement_id=p.id
                    AND a.admission_state='ELIGIBLE'
                    AND a.admission_policy_version='{ADMISSION_POLICY}'
               ),
               coalesce(p.ai_assessed_at>=current_date,false)
          FROM crm_procurements p
         WHERE p.crm_created_at>=current_date
        """
        unprocessed_ids=[
            i(r[0]) for r in rows(pq("crm",cohort_state_sql,30))
            if len(r)>=3 and r[1]=="t" and r[2]!="t" and i(r[0]) is not None
        ]
        if unprocessed_ids:
            pid_array="ARRAY["+",".join(str(pid) for pid in unprocessed_ids)+"]::bigint[]"
            queue_processing_sql=f"""
            SELECT 'PROCESSING',count(*)
              FROM document_processing_queue
             WHERE pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
               AND status='PROCESSING'
               AND procurement_id=ANY({pid_array})
            """
            qp=rows(pq("document_intelligence",queue_processing_sql,30))
            if qp:
                out["today"]["in_progress_from_received"]=(
                    i(out["today"].get("in_progress_from_received")) or 0
                )+(i(qp[0][1]) or 0)

        doc_sql=f"""
        SELECT count(*) FILTER (WHERE status IN
                 ('PENDING','PRE_RESEARCH_WAITING','RETRY','RETRYABLE')),
               count(*) FILTER (WHERE status IN ('PROCESSING','RUNNING')),
               count(*) FILTER (WHERE status='COMPLETED' AND completed_at>=current_date),
               count(*) FILTER (WHERE status='FAILED'),
               count(*) FILTER (WHERE status='NO_LINKS')
          FROM document_processing_queue
         WHERE pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
        """
        dr=rows(pq("document_intelligence",doc_sql,30))
        if dr:
            out["documents"].update({"waiting":i(dr[0][0]),"working":i(dr[0][1]),
                                     "done_today":i(dr[0][2]),"errors":i(dr[0][3]),
                                     "no_links":i(dr[0][4])})
        parsed_sql="""
        SELECT count(*) FILTER (
                 WHERE status='COMPLETED'
                   AND coalesce(completed_at, created_at) >= current_date)
          FROM document_processing_results
         WHERE pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
        """
        pr=i(pq("document_intelligence",parsed_sql,30))
        if pr is not None:
            out["documents"]["parsed_today"]=pr
        job_sql="""
        WITH last_jobs AS (
          SELECT completed_at FROM document_processing_queue
           WHERE status='COMPLETED' AND completed_at IS NOT NULL
             AND pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
           ORDER BY completed_at DESC LIMIT 30
        )
        SELECT completed_at FROM last_jobs ORDER BY completed_at
        """
        jr=[r[0] for r in rows(pq("document_intelligence",job_sql,30))]
        out["documents"]["throughput_per_hour"]=_rate_from_last_jobs(jr)

        out["model"]=model_candidate_pool_metrics()

        com_sql="""
        SELECT count(DISTINCT procurement_id),
               count(DISTINCT procurement_id) FILTER (WHERE current_effective_medal IS NOT NULL),
               count(DISTINCT procurement_id) FILTER (WHERE confirmed_base_medal IS NOT NULL),
               count(*),
               count(DISTINCT procurement_id) FILTER (WHERE created_at>=current_date),
               count(DISTINCT procurement_id) FILTER
                 (WHERE created_at>=current_date-interval '1 day' AND created_at<current_date)
          FROM crm_procurement_category_opportunities WHERE status='CURRENT'
        """
        cr=rows(pq("crm",com_sql,30))
        if cr:
            out["commercial"].update({"all_current_objects":i(cr[0][0]),
                                      "with_commerce":i(cr[0][1]),
                                      "all_current_document_confirmed":i(cr[0][2]),
                                      "all_current_category_opportunities":i(cr[0][3]),
                                      "objects":i(cr[0][0]),
                                      "document_confirmed":i(cr[0][2]),
                                      "category_opportunities":i(cr[0][3]),
                                      "result_today":i(cr[0][4]),
                                      "result_yesterday":i(cr[0][5])})
        medal_sql=f"""
        WITH best AS (
          SELECT procurement_id,
                 (array_agg(coalesce(current_effective_medal,'UNSCORED')
                   ORDER BY CASE coalesce(current_effective_medal,'UNSCORED')
                     WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2 WHEN 'BRONZE' THEN 3
                     WHEN 'WOOD' THEN 4 ELSE 5 END))[1] AS best_medal
            FROM crm_procurement_category_opportunities
           WHERE status='CURRENT' GROUP BY procurement_id
        )
        SELECT a.source_lifecycle,b.best_medal,count(*)
          FROM crm_procurement_scope_authority a JOIN best b ON b.procurement_id=a.procurement_id
         WHERE a.admission_state='ELIGIBLE'
           AND a.admission_policy_version='{ADMISSION_POLICY}'
           AND a.source_lifecycle IN ('OPEN','AWARDED')
         GROUP BY 1,2
        """
        for r in rows(pq("crm",medal_sql,30)):
            key="open" if r[0]=="OPEN" else "awarded"
            out["commercial"][key][r[1] or "UNSCORED"]=i(r[2])
        live_sql=f"""
        WITH best AS (
          SELECT procurement_id,
                 (array_agg(coalesce(current_effective_medal,'UNSCORED')
                   ORDER BY CASE coalesce(current_effective_medal,'UNSCORED')
                     WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2 WHEN 'BRONZE' THEN 3
                     WHEN 'WOOD' THEN 4 ELSE 5 END))[1] AS best_medal
            FROM crm_procurement_category_opportunities
           WHERE status='CURRENT' GROUP BY procurement_id
        )
        SELECT a.procurement_id,a.source_lifecycle,b.best_medal
          FROM crm_procurement_scope_authority a JOIN best b ON b.procurement_id=a.procurement_id
         WHERE a.admission_state='ELIGIBLE'
           AND a.admission_policy_version='{ADMISSION_POLICY}'
           AND a.source_lifecycle IN ('OPEN','AWARDED')
        """
        live_rows=[(int(r[0]),r[1],r[2]) for r in rows(pq("crm",live_sql,30))]
        live_pids={x[0] for x in live_rows}
        open_pids={x[0] for x in live_rows if x[1]=="OPEN"}
        award_pids={x[0] for x in live_rows if x[1]=="AWARDED"}
        live_stats_sql=f"""
        SELECT count(*),count(DISTINCT o.procurement_id) FILTER
                 (WHERE o.confirmed_base_medal IS NOT NULL)
          FROM crm_procurement_category_opportunities o
          JOIN crm_procurement_scope_authority a ON a.procurement_id=o.procurement_id
         WHERE o.status='CURRENT' AND a.admission_state='ELIGIBLE'
           AND a.admission_policy_version='{ADMISSION_POLICY}'
           AND a.source_lifecycle IN ('OPEN','AWARDED')
        """
        ls=rows(pq("crm",live_stats_sql,30))
        if ls:
            out["commercial"]["category_opportunities_live"]=i(ls[0][0])
            out["commercial"]["document_confirmed_live"]=i(ls[0][1])
        out["commercial"]["live_total"]=len(live_pids)
        open_sum=sum(int(v or 0) for v in out["commercial"]["open"].values())
        award_sum=sum(int(v or 0) for v in out["commercial"]["awarded"].values())
        out["commercial"]["medal_invariant_ok"]=(open_sum==len(open_pids) and award_sum==len(award_pids))
        attr_sql="""
        SELECT o.procurement_id,
               coalesce(a.source_lifecycle,'NO_SCOPE_AUTHORITY'),
               coalesce(a.admission_state,'NO_SCOPE_AUTHORITY'),
               coalesce(o.commercial_state,'NULL'),
               coalesce(o.opportunity_track,'NULL')
          FROM crm_procurement_category_opportunities o
          LEFT JOIN crm_procurement_scope_authority a ON a.procurement_id=o.procurement_id
         WHERE o.status='CURRENT'
        """
        attrs={}
        for pid,lifecycle,admission,cstate,track in rows(pq("crm",attr_sql,40)):
            pid=int(pid); attrs.setdefault(pid,{"lifecycle":lifecycle,"admission":admission,"states":set(),"tracks":set()})
            if cstate!="NULL": attrs[pid]["states"].add(cstate)
            if track!="NULL": attrs[pid]["tracks"].add(track)
        excluded=sorted(set(attrs)-live_pids)
        from collections import Counter as _Counter
        grouped=_Counter()
        for pid in excluded:
            a=attrs[pid]
            grouped[(a["lifecycle"],a["admission"],",".join(sorted(a["states"])),",".join(sorted(a["tracks"])))]+=1
        out["commercial"]["excluded_count"]=len(excluded)
        out["commercial"]["excluded_breakdown"]=[
            {"source_lifecycle":k[0],"admission_state":k[1],"commercial_state":k[2],
             "opportunity_track":k[3],"procurements":n}
            for k,n in sorted(grouped.items(),key=lambda x:(x[0][0],x[0][1],x[0][2],x[0][3]))
        ]

        arrivals_sql="""
        SELECT count(DISTINCT id) FROM crm_procurements
         WHERE crm_created_at>=now()-interval '60 minutes'
        """
        ar=rows(pq("crm",arrivals_sql,20))
        a_n=i(ar[0][0]) if ar else None
        out["rates"]["arrivals_per_hour"]=float(a_n) if a_n else None
        current_ids = current_research_authority_ids()
        current_array = "ARRAY[" + ",".join(str(pid) for pid in current_ids) + "]::bigint[]"
        proc_sql=f"""
        SELECT count(DISTINCT procurement_id) FROM document_processing_queue
         WHERE status='COMPLETED' AND completed_at>=now()-interval '60 minutes'
           AND pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
           AND procurement_id=ANY({current_array})
           AND category_context->>'commercial_authority_version'='CURRENT_CATEGORY_OPPORTUNITY_V1'
           AND category_context->>'current_research_eligible'='true'
        """
        pr=rows(pq("document_intelligence",proc_sql,20))
        p_n=i(pr[0][0]) if pr else None
        out["rates"]["processed_per_hour"]=float(p_n) if p_n else None

        rolling_sql=f"""
        SELECT
          (SELECT count(DISTINCT p.id) FROM crm_procurements p
            WHERE p.crm_created_at>=current_date-interval '5 days'
              AND p.crm_created_at<current_date
              AND EXISTS (SELECT 1 FROM crm_procurement_scope_authority a
                 WHERE a.procurement_id=p.id AND a.admission_state='ELIGIBLE'
                   AND a.admission_policy_version='{ADMISSION_POLICY}')),
          (SELECT count(DISTINCT p.id) FROM crm_procurements p
            WHERE p.ai_assessed_at>=current_date-interval '5 days'
              AND p.ai_assessed_at<current_date
              AND EXISTS (SELECT 1 FROM crm_procurement_scope_authority a
                 WHERE a.procurement_id=p.id AND a.admission_state='ELIGIBLE'
                   AND a.admission_policy_version='{ADMISSION_POLICY}')
              AND (upper(coalesce(p.ai_assessment_status,'')) IN ('COMPLETED','NEEDS_REVIEW')
                   OR (upper(coalesce(p.ai_assessment_status,''))='FAILED'
                       AND coalesce(p.ai_routing_attempt_count,0)>={MAX_ROUTING_ATTEMPTS}))),
          (SELECT count(DISTINCT p.crm_created_at::date) FROM crm_procurements p
            WHERE p.crm_created_at>=current_date-interval '5 days'
              AND p.crm_created_at<current_date
              AND EXISTS (SELECT 1 FROM crm_procurement_scope_authority a
                 WHERE a.procurement_id=p.id AND a.admission_state='ELIGIBLE'
                   AND a.admission_policy_version='{ADMISSION_POLICY}')),
          (SELECT count(DISTINCT p.ai_assessed_at::date) FROM crm_procurements p
            WHERE p.ai_assessed_at>=current_date-interval '5 days'
              AND p.ai_assessed_at<current_date
              AND EXISTS (SELECT 1 FROM crm_procurement_scope_authority a
                 WHERE a.procurement_id=p.id AND a.admission_state='ELIGIBLE'
                   AND a.admission_policy_version='{ADMISSION_POLICY}')
              AND (upper(coalesce(p.ai_assessment_status,'')) IN ('COMPLETED','NEEDS_REVIEW')
                   OR (upper(coalesce(p.ai_assessment_status,''))='FAILED'
                       AND coalesce(p.ai_routing_attempt_count,0)>={MAX_ROUTING_ATTEMPTS})))
        """
        rr=rows(pq("crm",rolling_sql,40))
        if rr:
            arrivals=i(rr[0][0]) or 0
            processed=i(rr[0][1]) or 0
            arrival_days=i(rr[0][2]) or 0
            processed_days=i(rr[0][3]) or 0
            coverage=round(100.0*processed/arrivals,1) if arrivals else None
            balance=round(100.0*(processed-arrivals)/arrivals,1) if arrivals else None
            out["rolling_5d"]={
                "available":arrivals>0,"window_days":5,
                "arrivals":arrivals,"processed":processed,
                "avg_arrivals_per_day":round(arrivals/5.0,1),
                "avg_processed_per_day":round(processed/5.0,1),
                "coverage_pct":coverage,"balance_pct":balance,
                "state":"GREEN" if arrivals and processed>=arrivals else ("RED" if arrivals else "UNKNOWN"),
                "arrival_days":arrival_days,"processed_days":processed_days,
                "warming_up":arrival_days<5 or processed_days<5,
            }

        for k in ("received","admitted","processed","result_today"):
            if k=="result_today":
                continue
            if out["today"].get(k) is not None and out["yesterday"].get(k) is not None:
                out["delta"][k]=out["today"][k]-out["yesterday"][k]
        if out["model"].get("confirmed_today") is not None:
            out["delta"]["confirmed_today"]=out["model"]["confirmed_today"]
    except Exception as e:
        out["available"]=False
        out["error"]=str(e)
    return out

def heavy():
    t0=time.time()
    # CURRENT STATE (scope authority + medals)
    scope={}
    for r in rows(pq("crm","SELECT source_lifecycle, admission_state, count(*) FROM crm_procurement_scope_authority GROUP BY 1,2")):
        scope.setdefault(r[0],{})[r[1]]=int(r[2])
    med={}
    for r in rows(pq("crm","SELECT a.source_lifecycle, COALESCE(o.current_effective_medal,'UNSCORED'), count(DISTINCT a.procurement_id) FROM crm_procurement_scope_authority a LEFT JOIN crm_procurement_category_opportunities o ON o.procurement_id=a.procurement_id WHERE a.source_lifecycle IN ('OPEN','AWARDED') AND a.admission_state='ELIGIBLE' GROUP BY 1,2",30)):
        med.setdefault(r[0],{})[r[1]]=int(r[2])
    # Queue totals use the same current authority and generation marker as consumers.
    eligible_ids = current_research_authority_ids()
    eligible_array = "ARRAY[" + ",".join(str(pid) for pid in eligible_ids) + "]::bigint[]"
    current_commercial_count = i(pq(
        "crm",
        "SELECT count(DISTINCT procurement_id) FROM crm_procurement_category_opportunities WHERE status='CURRENT'",
        30,
    ))
    current_queue_scope = f"""pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
       AND procurement_id=ANY({eligible_array})
       AND category_context->>'commercial_authority_version'='CURRENT_CATEGORY_OPPORTUNITY_V1'
       AND category_context->>'current_research_eligible'='true'"""
    q={}
    for r in rows(pq("document_intelligence",f"""SELECT status, count(DISTINCT procurement_id)
      FROM document_processing_queue
     WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING')
       AND {current_queue_scope}
     GROUP BY 1""")):
        q[r[0]]=int(r[1])
    adm={}
    for r in rows(pq("document_intelligence",f"""SELECT COALESCE(category_context->>'admission_state','-'), count(DISTINCT procurement_id)
      FROM document_processing_queue
     WHERE status IN ('PENDING','PRE_RESEARCH_WAITING')
       AND {current_queue_scope}
     GROUP BY 1""")):
        adm[r[0]]=int(r[1])
    cl=[]
    claimable_sql = f"""SELECT COALESCE(research_prior_band,'UNSCORED'), count(DISTINCT procurement_id)
      FROM document_processing_queue q
     WHERE q.status IN ('PENDING','PRE_RESEARCH_WAITING')
       AND q.pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
       AND q.procurement_id=ANY({eligible_array})
       AND q.category_context->>'commercial_authority_version'='CURRENT_CATEGORY_OPPORTUNITY_V1'
       AND q.category_context->>'current_research_eligible'='true'
       AND q.selected_documents IS NOT NULL
       AND jsonb_typeof(q.selected_documents)='array'
       AND q.selected_documents <> '[]'::jsonb
       AND (q.research_action='FACTUAL_FEEDER_ADMITTED'
         OR q.category_context->>'AI_QUEUE_ADMISSION_GATE'='YES'
         OR (q.plan_version='queue_v2'
             AND q.research_action_v2 IN ('DOCUMENT_RESEARCH_REQUIRED','DOCUMENT_CONFIRMATION_REQUIRED')
             AND q.category_context->>'admission_state'='ELIGIBLE'))
       AND coalesce(q.category_context->>'legacy_revalidation_status','') NOT IN ('REQUIRED','LEGACY_HOLD')
       AND (q.plan_version IS DISTINCT FROM 'queue_v2'
            OR coalesce(q.research_action_v2,'') IN ('DOCUMENT_RESEARCH_REQUIRED','DOCUMENT_CONFIRMATION_REQUIRED'))
     GROUP BY 1 ORDER BY 1"""
    for r in rows(pq("document_intelligence",claimable_sql,30)):
        cl.append({"band":r[0],"count":int(r[1])})
    # FLOW TODAY
    slice_sql="SELECT count(*), count(*) FILTER (WHERE source_table='reestr_contract_44_fz'), count(*) FILTER (WHERE source_table='reestr_contract_223_fz'), count(*) FILTER (WHERE crm_stage='torgi'), count(*) FILTER (WHERE crm_stage='razygranye') FROM crm_procurements WHERE id > (SELECT max(id)-20000 FROM crm_procurements) AND crm_created_at >= current_date"
    rs=[x.strip() for x in pq("crm",slice_sql,30).split("|")]
    rec={"total":i(rs[0]),"s44":i(rs[1]),"s223":i(rs[2]),"torgi":i(rs[3]),"awarded":i(rs[4])}
    cat=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_procurement_category_opportunities WHERE created_at >= current_date",30)
    cat_all=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_procurement_category_opportunities",30)
    medal_ch=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_category_opportunity_medal_history WHERE evaluated_at >= current_date AND previous_effective_medal IS DISTINCT FROM new_effective_medal",30)
    medal_new=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_category_opportunity_medal_history WHERE evaluated_at >= current_date AND previous_effective_medal IS NULL AND new_effective_medal IS NOT NULL",30)
    queued=pq("document_intelligence",f"SELECT count(DISTINCT procurement_id) FROM document_processing_queue WHERE created_at >= current_date AND {current_queue_scope}",30)
    model=pq("crm","SELECT count(DISTINCT id) FROM crm_procurements WHERE id > (SELECT max(id)-20000 FROM crm_procurements) AND ai_assessed_at >= current_date",30)
    # PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1: компактная read-only аналитика.
    # Тяжёлые all-time COUNT не делаем: validator — только за сегодня (29ms),
    # очередь/ошибки — по ограниченным выборкам.
    docstats={}
    for r in rows(pq("document_intelligence",f"SELECT status, count(*) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING') AND {current_queue_scope} GROUP BY 1")):
        docstats[r[0]]=i(r[1])
    for r in rows(pq("document_intelligence",f"SELECT status, count(DISTINCT procurement_id) FROM document_processing_queue WHERE status IN ('COMPLETED','FAILED') AND completed_at >= current_date AND {current_queue_scope} GROUP BY 1")):
        docstats['TODAY_'+r[0]]=i(r[1])
    validator={}
    for r in rows(pq("document_intelligence","SELECT CASE WHEN upper(coalesce(d.validation_status,'')) IN ('UNKNOWN','RAW','PENDING') AND d.validated_at IS NULL THEN 'PENDING' ELSE upper(coalesce(d.validation_status,'UNKNOWN')) END AS st, count(*) FROM document_match_details d JOIN document_matches m ON m.id=d.match_id WHERE m.created_at >= current_date GROUP BY 1")):
        validator[r[0]]=i(r[1])
    recovery={}
    for r in rows(pq("document_intelligence","SELECT COALESCE(outcome,'?'), count(*) FROM document_extraction_outcomes WHERE updated_at >= current_date GROUP BY 1")):
        recovery[r[0]]=i(r[1])
    for r in rows(pq("document_intelligence","SELECT CASE WHEN file_name ILIKE '%.rtf' THEN 'RTF' WHEN file_name ILIKE '%.xls' THEN 'XLS' WHEN file_name ILIKE '%.doc' THEN 'DOC' ELSE 'OTHER' END, count(*) FROM document_files WHERE error_message ILIKE 'Unsupported format%' GROUP BY 1")):
        recovery['UNSUPPORTED_'+r[0]]=i(r[1])
    errors=[]
    for r in rows(pq("document_intelligence",f"SELECT id, procurement_id, coalesce(last_error,'') FROM document_processing_queue WHERE status='FAILED' AND {current_queue_scope} ORDER BY id DESC LIMIT 5")):
        errors.append({"id":i(r[0]),"pid":i(r[1]),"err":(r[2] or "")[:160]})
    cc=pq("crm","SELECT count(*), count(*) FILTER (WHERE confirmed_base_medal IS NOT NULL) FROM crm_procurement_category_opportunities WHERE status='CURRENT'")
    cat_conf=[i(x.strip()) for x in cc.split("|")] if "|" in cc else [None,None]
    prod_state=svc("crm-ai-assessment-runner.service")
    shadow_state=svc("crm-v3-shadow-predictor.service")
    flow={"received":rec,"category_today":i(cat),"category_total":i(cat_all),"medal_new":i(medal_new),"medal_changed":i(medal_ch),"queued_today":i(queued),"model_processed":i(model),
          "production":prod_state,"production_label":svc_label(prod_state),
          "shadow":shadow_state,"shadow_label":svc_label(shadow_state)}
    q["current_commercial_procurements"] = current_commercial_count
    q["current_research_eligible_procurements"] = len(eligible_ids)
    CACHE["data"]={"scope":scope,"medals":med,"queue":q,"admission":adm,"claimable":cl,"claimable_total":sum(x['count'] for x in cl),
                   "flow":flow,"docstats":docstats,"validator":validator,"recovery":recovery,
                   "errors":errors,"cat_conf":cat_conf,"daily":daily_kpis(),
                   "command":command_center_metrics(),
                   "heavy_ms":int((time.time()-t0)*1000),"ts":time.strftime('%H:%M:%S')}
    CACHE["ts"]=time.time()
def loop():
    while True:
        try: heavy()
        except Exception as e: CACHE["data"]={"err":str(e)}
        time.sleep(90)
def normalization_runtime_metrics(running=False, unit_name=None):
    if NORMALIZATION_CACHE["data"] is None or time.time()-NORMALIZATION_CACHE["ts"]>=60:
        sql=("WITH latest AS (SELECT DISTINCT ON (procurement_id) status,updated_at "
             "FROM estimate_row_normalization_procurements "
             "ORDER BY procurement_id,updated_at DESC,run_id DESC) "
             "SELECT count(*) FILTER (WHERE status<>'COMPLETED'), "
             "max(updated_at) FILTER (WHERE status='COMPLETED'), "
             "count(*) FILTER (WHERE status='COMPLETED' AND updated_at>=now()-interval '1 hour'), "
             "count(*) FILTER (WHERE status='COMPLETED' AND updated_at>=now()-interval '24 hours') FROM latest")
        try:
            r=rows(pq("document_intelligence",sql,8)); v=r[0] if r else []
            data={"pending":i(v[0]) if len(v)>0 else None,"last_success":v[1] if len(v)>1 else None,
                  "normalized_procurements_last_1h":i(v[2]) if len(v)>2 else None,
                  "normalized_procurements_last_24h":i(v[3]) if len(v)>3 else None}
        except Exception:
            data={"pending":None,"last_success":None,"normalized_procurements_last_1h":None,
                  "normalized_procurements_last_24h":None}
        NORMALIZATION_CACHE.update({"data":data,"ts":time.time()})
    return {"implemented":True,"running":running,"state":"RUNNING" if running else "OFF","unit":unit_name,**NORMALIZATION_CACHE["data"]}

def runtime_snapshot():
    """Bounded live process/service attribution; no business-state writes."""
    try:
        proc=subprocess.run(["ps","-eo","pid=,ppid=,pcpu=,etimes=,args=","--sort=-pcpu"],capture_output=True,text=True,timeout=3).stdout
        procs=[]
        for line in proc.splitlines():
            p=line.strip().split(None,4)
            if len(p)==5:
                try: procs.append({"pid":int(p[0]),"ppid":int(p[1]),"cpu":float(p[2]),"elapsed":int(p[3]),"cmd":p[4]})
                except ValueError: pass
        by_pid={p["pid"]:p for p in procs}
        def unit(pid):
            try:
                cg=open("/proc/%d/cgroup"%pid).read()
                m=re.search(r"([^/]+\.service)",cg)
                return m.group(1) if m else None
            except Exception: return None
        units=subprocess.run(["systemctl","list-units","--all","--type=service","--no-legend"],capture_output=True,text=True,timeout=4).stdout
        names=[x.split()[0] for x in units.splitlines() if re.search(r"document|tender-docs|normaliz",x,re.I)]
        relevant=["crm-ai-assessment-runner.service","crm-v3-factual-feeder.service","crm-v3-autonomous-worker.service","crm-procurement-sync.service","postgresql@17-main.service","ollama.service"]+names
        states={}
        for name in dict.fromkeys(relevant):
            output=subprocess.run(["systemctl","show",name,"-p","ActiveState","-p","MainPID"],capture_output=True,text=True,timeout=2).stdout
            fields=dict(line.split("=",1) for line in output.splitlines() if "=" in line)
            main_pid=i(fields.get("MainPID"))
            states[name]={"state":fields.get("ActiveState","unknown"),"pid":main_pid if main_pid else None}
        gpu_out=subprocess.run(["nvidia-smi","--query-compute-apps=pid,process_name,used_gpu_memory","--format=csv,noheader"],capture_output=True,text=True,timeout=4).stdout
        model_out=subprocess.run(["ollama","ps"],capture_output=True,text=True,timeout=3).stdout.splitlines()
        gpu_model=subprocess.run(["nvidia-smi","--query-gpu=name","--format=csv,noheader"],capture_output=True,text=True,timeout=3).stdout.strip().splitlines()
        gpu_procs=parse_gpu_compute_apps(gpu_out,by_pid,unit)
        for item in gpu_procs:
            item["elapsed"]=by_pid.get(item["pid"],{}).get("elapsed")
            item["cpu"]=by_pid.get(item["pid"],{}).get("cpu")
        aj=subprocess.run(["journalctl","-u","crm-ai-assessment-runner.service","-n","40","--no-pager","-o","short-unix"],capture_output=True,text=True,timeout=5).stdout.splitlines()
        current=parse_current_assessment(aj)
        started_epoch=None
        for log_line in aj:
            start_match=re.search(r"^(\d+(?:\.\d+)?)\s+.*Processing CRM ID (\d+)",log_line)
            if start_match and int(start_match.group(2))==current: started_epoch=float(start_match.group(1))
            if current and re.search(r"persisted .*procurement_id=%d"%current,log_line): started_epoch=None
        job_elapsed=max(0,int(time.time()-started_epoch)) if started_epoch else None
        assessment=states.get("crm-ai-assessment-runner.service",{})
        apid=assessment.get("pid")
        if apid:
            child=next((p for p in procs if p["ppid"]==apid and "crm_ai_assessment_runner.py" in p["cmd"]),None)
            if child: apid=child["pid"]
        contract=None
        if current is not None:
            r=rows(pq("crm","SELECT contract_number FROM crm_procurements WHERE id=%d"%current,4))
            contract=r[0][0] if r and r[0] else None
        feeder_log=subprocess.run(["journalctl","-u","crm-v3-factual-feeder.service","-n","1","--no-pager","-o","cat"],capture_output=True,text=True,timeout=3).stdout.strip()
        docs=states.get("crm-ai-assessment-runner.service")
        doc_units=[(k,v) for k,v in states.items() if re.search(r"document|tender-docs",k,re.I) and not re.search(r"sweeper|retention|probe",k,re.I)]
        running_docs=sum(v["state"]=="active" and v["pid"] not in (None,0) for _,v in doc_units)
        docqueue=((CACHE.get("data") or {}).get("command") or {}).get("documents",{})
        docstate=document_runtime_counts(docqueue.get("waiting"),docqueue.get("working"),running_docs)
        top=[dict(p,unit=unit(p["pid"])) for p in procs if not p["cmd"].lstrip().startswith("ps -eo")][:8]
        events=[]
        journal_units=["-u","crm-ai-assessment-runner.service","-u","crm-v3-factual-feeder.service"]
        for name,_ in doc_units: journal_units += ["-u",name]
        ev=subprocess.run(["journalctl",*journal_units,"-n","60","--since","20 minutes ago","--no-pager","-o","short-iso"],capture_output=True,text=True,timeout=6).stdout.splitlines()
        for line in ev[-20:]:
            idm=re.search(r"(?:CRM ID|procurement_id=)(\d+)",line)
            stage="assessment" if "assessment" in line.lower() or "crm-ai-assessment" in line.lower() else ("feeder" if "feeder" in line.lower() else "documents")
            events.append({"time":line[:25],"stage":stage,"event":line[-180:],"procurement":idm.group(1) if idm else "—"})
        arbiter={}
        try:
            with open("/var/lib/crm-v3-canary/gpu_arbiter/state.json") as fh: arbiter=json.load(fh)
        except Exception: pass
        arbiter_age=None
        try: arbiter_age=max(0,int((datetime.now(timezone.utc)-datetime.fromisoformat(arbiter["updated_at"])).total_seconds()))
        except Exception: pass
        for e in events:
            e["result"]="FAILED" if re.search(r"failed|error|exception",e["event"],re.I) else ("DONE" if re.search(r"persisted|completed|success",e["event"],re.I) else "EVENT")
            e["duration"]=(re.search(r"(\d+(?:\.\d+)?s)",e["event"]) or [None,None])[1]
        failed_by_procurement={}
        for event in events:
            if event["result"]=="FAILED" and event["procurement"] not in ("?", "-"):
                failed_by_procurement[event["procurement"]]=failed_by_procurement.get(event["procurement"],0)+1
        failed_loop_detected=any(count>1 for count in failed_by_procurement.values())
        assessment_consecutive_failures=0
        for event in reversed(events):
            if event["stage"]!="assessment": continue
            if event["result"]=="FAILED": assessment_consecutive_failures+=1
            elif event["result"]=="DONE": break
        current_stage="MODEL_INFERENCE" if current else ("IDLE" if assessment.get("state")=="active" else assessment.get("state","UNKNOWN").upper())
        normalization_unit=next((k for k in states if "normaliz" in k.lower()),None)
        normalization=normalization_runtime_metrics(bool(normalization_unit and states[normalization_unit]["state"]=="active"),normalization_unit)
        gpu_caller=unit(i(arbiter.get("holder_pid"))) if arbiter_age is not None and arbiter_age<=30 and arbiter.get("holder_pid") else None
        if not gpu_caller and gpu_procs: gpu_caller=gpu_procs[0].get("unit")
        return {"cpu_top":top,"gpu_processes":gpu_procs,"gpu_model":gpu_model[0] if gpu_model else None,"gpu_active_model":model_out[1].strip() if len(model_out)>1 else None,"gpu_owner_unknown":bool(gpu_procs and not gpu_caller),"gpu_caller":gpu_caller,"services":states,"commercial":{"state":states.get("crm-procurement-sync.service",{}).get("state","unknown"),"unit":"crm-procurement-sync.service","pid":states.get("crm-procurement-sync.service",{}).get("pid")},"assessment":{"state":assessment.get("state"),"pid":apid,"procurement_id":current,"contract":contract,"elapsed":job_elapsed,"stage":current_stage,"batch_size":None,"batch_progress":None,"last_success":None,"last_failure":None,"consecutive_failures":assessment_consecutive_failures},"failed_loop_detected":failed_loop_detected,"feeder":{"state":states.get("crm-v3-factual-feeder.service",{}).get("state"),"last_event":feeder_log[-220:]},"documents":{"workers_running":running_docs,"workers_total":len(doc_units),"queue_working":docstate["processing"],"queue_ready":docstate["ready"],"stale":docstate["stale"],"state":docstate["state"]},"normalization":normalization,"autonomous":states.get("crm-v3-autonomous-worker.service",{}),"active_jobs":[{"stage":"ASSESSMENT","procurement_id":current,"contract":contract,"action":current_stage,"progress":None,"elapsed":job_elapsed,"started_at":time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(started_epoch)) if started_epoch else None,"pid":apid,"cpu":next((p["cpu"] for p in procs if p["pid"]==apid),None),"gpu":bool(gpu_procs)}] if current else [],"feeder_metrics":{"last_cycle":feeder_log[-220:],"duration":None,"current_commercial_seen":None,"actionable":None,"admitted":None,"already_done":None,"no_documents":None,"lifecycle_closed":None},"events":events,"load":list(os.getloadavg()) if hasattr(os,"getloadavg") else [],"sampled_at":time.strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        return {"error":str(e),"sampled_at":time.strftime("%Y-%m-%d %H:%M:%S")}

def runtime_loop():
    while True:
        started=time.monotonic()
        RUNTIME["data"]=runtime_snapshot()
        RUNTIME["data"]["collector_ms"]=round((time.monotonic()-started)*1000)
        RUNTIME["ts"]=time.time(); time.sleep(10)

def problems():
    d=CACHE["data"]; pr=[]; f=d.get("flow",{})
    if f.get("production")!="active":
        label=f.get("production_label") or svc_label(f.get("production"))
        pr.append(["WARNING",f"Инференс продакшена: {label}",
                   "production assessments сейчас не материализуются"])
    if f.get("category_today")==0: pr.append(["WARNING","Сегодня нет материализованных категорий","0 возможностей создано сегодня"])
    if f.get("received",{}) and f["received"].get("total")==0: pr.append(["CRITICAL","Сегодня нет новых закупок","остановился приём?"])
    pr.append(["INFO","Текущих коммерческих закупок: %s" % (d.get("queue",{}).get("current_commercial_procurements") or 0),"CURRENT opportunities"])
    pr.append(["INFO","Требуют исследования: %s" % (d.get("queue",{}).get("current_research_eligible_procurements") or 0),"текущая research authority"])
    pr.append(["INFO","Задач доступно для claim: %s" % d.get("claimable_total",0),"точный consumer predicate"])
    pr.append(["INFO","Задач в работе: %s" % (d.get("queue",{}).get("PROCESSING") or 0),"только текущая authority"])
    pr.append(["INFO","Завершено сегодня, закупок: %s" % (d.get("docstats",{}).get("TODAY_COMPLETED") or 0),"distinct procurement_id"])
    return pr

CONTOUR_COLS=("captured_at,eligible_total,processed_total,remaining_total,in_progress,"
 "deterministic_accept,no_commercial_entry,qwen_processed,classified_total,backlog_drain_remaining,"
 "gold,silver,bronze,wood,failed,blocked,document_pending,document_processing,"
 "document_completed_total,document_no_links,document_failed")
CONTOUR_KEYS=CONTOUR_COLS.split(",")+["age_sec","tag"]
def _snap_parse(line):
    p=line.split("|")
    if len(p)!=len(CONTOUR_KEYS): return None
    d={}
    for k,v in zip(CONTOUR_KEYS,p):
        v=v.strip()
        if v in ("","NULL","None"): d[k]=None
        else:
            try: d[k]=float(v) if ("." in v or "-" in v[1:]) else int(v)
            except ValueError: d[k]=v
    return d
def _contour_progress():
    c=CONTOUR_COLS
    sql=("(SELECT "+c+", EXTRACT(EPOCH FROM (NOW()-captured_at))::int, 'latest' FROM crm_contour_progress_snapshots ORDER BY captured_at DESC LIMIT 1) "
         "UNION ALL (SELECT "+c+", NULL, 'd24' FROM crm_contour_progress_snapshots WHERE captured_at BETWEEN NOW()-INTERVAL '24 hours 30 minutes' AND NOW()-INTERVAL '23 hours 30 minutes' ORDER BY abs(EXTRACT(EPOCH FROM (captured_at-(NOW()-INTERVAL '24 hours')))) LIMIT 1) "
         "UNION ALL (SELECT "+c+", EXTRACT(EPOCH FROM (NOW()-captured_at))::int, 'h1' FROM crm_contour_progress_snapshots WHERE captured_at BETWEEN NOW()-INTERVAL '90 minutes' AND NOW()-INTERVAL '30 minutes' ORDER BY abs(EXTRACT(EPOCH FROM (captured_at-(NOW()-INTERVAL '1 hour')))) LIMIT 1) "
         "UNION ALL (SELECT "+c+", EXTRACT(EPOCH FROM (NOW()-captured_at))::int, 'prior_day' FROM crm_contour_progress_snapshots WHERE captured_at<current_date ORDER BY captured_at DESC LIMIT 1) "
         "UNION ALL (SELECT "+c+", EXTRACT(EPOCH FROM (NOW()-captured_at))::int, 'first_today' FROM crm_contour_progress_snapshots WHERE captured_at>=current_date ORDER BY captured_at ASC LIMIT 1) "
         "UNION ALL (SELECT "+c+", EXTRACT(EPOCH FROM (NOW()-captured_at))::int, 'baseline' FROM crm_contour_progress_snapshots ORDER BY captured_at ASC LIMIT 1)")
    out={}
    for line in pq("crm",sql,12).splitlines():
        d=_snap_parse(line)
        if d: out[d["tag"]]=d
    return out
def _contour_cats():
    sql=("SELECT category_code,total,classified,unclassified,coverage_pct,EXTRACT(EPOCH FROM (NOW()-captured_at))::int,tag FROM ("
         "(SELECT category_code,total,classified,unclassified,coverage_pct,captured_at,'latest' tag FROM crm_contour_category_snapshots WHERE captured_at=(SELECT max(captured_at) FROM crm_contour_category_snapshots)) "
         "UNION ALL (SELECT category_code,total,classified,unclassified,coverage_pct,captured_at,'d24' tag FROM crm_contour_category_snapshots WHERE captured_at BETWEEN NOW()-INTERVAL '24 hours 30 minutes' AND NOW()-INTERVAL '23 hours 30 minutes')) s ORDER BY tag, coverage_pct DESC NULLS LAST")
    keys=["category_code","total","classified","unclassified","coverage_pct","age_sec","tag"]
    latest=[]; d24={}
    for line in pq("crm",sql,12).splitlines():
        p=line.split("|")
        if len(p)!=len(keys): continue
        d=dict(zip(keys,[x.strip() for x in p]))
        try: d["coverage_pct"]=float(d["coverage_pct"])
        except Exception: pass
        if d["tag"]=="latest": latest.append(d)
        elif d["tag"]=="d24": d24[d["category_code"]]=d
    return latest,d24
def contour():
    rows=_contour_progress(); latest=rows.get("latest")
    out={"available":bool(latest),"latest":latest,"delta":{},"delta_source":None}
    if not latest: return out
    day_start=rows.get("prior_day")
    day_start_source="prior_day"
    try:
        day_start_age=int(day_start.get("age_sec")) if day_start else None
    except (TypeError,ValueError):
        day_start_age=None
    if day_start and (day_start_age is None or day_start_age>DAY_START_MAX_AGE_SECONDS):
        # A missed timer must not anchor today's workload to an old outage
        # snapshot. Use the first fresh snapshot from today instead.
        day_start=rows.get("first_today")
        day_start_source="first_today_after_stale_prior_day"
    if not day_start:
        day_start=rows.get("first_today")
        day_start_source="first_today"
    if day_start:
        out["day_start"]=dict(day_start)
        out["day_start"]["source"]=day_start_source
    ref=rows.get("d24"); src="24h"
    if not ref:
        b=rows.get("baseline")
        if b and b.get("captured_at")!=latest.get("captured_at"): ref,src=b,"baseline"
    if ref:
        for k in ("processed_total","remaining_total","gold","silver","bronze","wood",
                  "deterministic_accept","no_commercial_entry","qwen_processed","document_completed_total"):
            if latest.get(k) is not None and ref.get(k) is not None: out["delta"][k]=latest[k]-ref[k]
        out["delta_source"]=src
    h1=rows.get("h1")
    if h1 and latest.get("remaining_total") is not None and h1.get("remaining_total") is not None:
        out["delta_1h"]={"remaining_total":latest["remaining_total"]-h1["remaining_total"]}
    else:
        out["delta_1h"]={}
    cats,d24=_contour_cats()
    for cc in cats:
        pv=d24.get(cc["category_code"])
        if pv and cc.get("coverage_pct") is not None and pv.get("coverage_pct") is not None:
            cc["coverage_delta_pp"]=round(cc["coverage_pct"]-pv["coverage_pct"],1)
    out["categories"]=cats
    return out

def daily_work_contract(command, contour_data):
    today=(command or {}).get("today") or {}
    yesterday=(command or {}).get("yesterday") or {}
    latest=(contour_data or {}).get("latest") or {}
    researchable=today.get("researchable_from_received")
    processed=today.get("processed_from_received")
    in_progress=today.get("in_progress_from_received")
    daily_remaining=(max(0,researchable-processed)
                     if researchable is not None and processed is not None else None)
    daily_pct=(round(100.0*processed/researchable,1)
               if researchable not in (None,0) and processed is not None else None)
    current_remaining=latest.get("remaining_total")
    eligible=latest.get("eligible_total")
    processed_total=latest.get("processed_total")
    contour_pct=(round(1000.0*processed_total/eligible)/10
                 if eligible and processed_total is not None else None)
    routing_backlog=routing_backlog_count()
    documents=(command or {}).get("documents") or {}
    daily_work={
        "received_today":today.get("received"),
        "researchable_today":researchable,
        "actionable_today":researchable,
        "with_initial_signal":today.get("with_initial_signal"),
        "without_initial_signal":today.get("without_initial_signal"),
        "no_commercial_signal":today.get("without_initial_signal"),
        "in_progress_from_day_work_set":in_progress,
        "daily_workload":researchable,
        "processed_from_day_work_set":processed,
        "remaining_from_day_work_set":daily_remaining,
        "processed_all_cohorts_today":today.get("processed"),
        "daily_progress_pct":daily_pct,
        "current_remaining":current_remaining,
        "routing_backlog":routing_backlog,
        "document_queue_pending":documents.get("waiting"),
        "previous_day":{
            "received":yesterday.get("received"),
            "researchable":yesterday.get("researchable_from_received"),
            "with_initial_signal":yesterday.get("with_initial_signal"),
            "without_initial_signal":yesterday.get("without_initial_signal"),
            "processed":yesterday.get("processed"),
        },
    }
    contour_total={
        "eligible_total":eligible,
        "processed_total":processed_total,
        "remaining_total":current_remaining,
        "progress_pct":contour_pct,
        "snapshot_age_sec":latest.get("age_sec"),
        "captured_at":latest.get("captured_at"),
    }
    return daily_work,contour_total

def cached_contour():
    if CONTOUR_CACHE["data"] is None or time.time()-CONTOUR_CACHE["ts"]>=45:
        CONTOUR_CACHE["data"]=contour()
        CONTOUR_CACHE["ts"]=time.time()
    return CONTOUR_CACHE["data"]

def cached_today_truth(live_document_workers=0):
    if TODAY_TRUTH_CACHE["data"] is None or time.time()-TODAY_TRUTH_CACHE["ts"]>=45:
        try:
            TODAY_TRUTH_CACHE["data"]=collect_today_truth(
                truth_pq,parse_rows_fn=rows,live_document_workers=live_document_workers,
                captured_at=time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            )
        except Exception as exc:
            TODAY_TRUTH_CACHE["data"]={"available":False,"error":str(exc)}
        TODAY_TRUTH_CACHE["ts"]=time.time()
    return TODAY_TRUTH_CACHE["data"]

def snapshot():
    d=json.loads(json.dumps(CACHE["data"]))
    cpu=cpu_metrics()
    temps=temperatures()
    gpu_data=gpu()
    disk_data=disks()
    pr=problems()
    contour_data=cached_contour()
    daily_work,contour_total=daily_work_contract(d.get("command") or {},contour_data)
    runtime=RUNTIME.get("data") or {}
    truth=cached_today_truth((runtime.get("documents") or {}).get("workers_running",0))
    if temps.get("status")=="CRITICAL":
        pr.append(["CRITICAL","Перегрев CPU: %sC" % temps.get("display"),temps.get("source") or "source unknown"])
    elif temps.get("status")=="WARNING":
        pr.append(["WARNING","Высокая температура CPU: %sC" % temps.get("display"),temps.get("source") or "source unknown"])
    severe=[p[0] for p in pr]
    incomplete=(
        cpu.get("total") is None or temps.get("display") is None
        or gpu_data is None or not disk_data
        or not (d.get("command") or {}).get("available",False)
    )
    if "CRITICAL" in severe or temps.get("status")=="CRITICAL":
        sys_status={"state":"CRITICAL","label":"КРИТИЧЕСКАЯ ОШИБКА"}
    elif "WARNING" in severe or temps.get("status")=="WARNING" or incomplete:
        sys_status={"state":"WARNING","label":"ТРЕБУЕТ ВНИМАНИЯ"}
    else:
        sys_status={"state":"OK","label":"СИСТЕМА РАБОТАЕТ"}
    # cpu/temp оставлены числовыми для обратной совместимости старых клиентов;
    # расширенный контракт — cpu_detail / temperatures.
    d.update({"cpu":cpu.get("total"),"cpu_detail":cpu,"mem":mem(),"gpu":gpu_data,
              "temp":temps.get("display"),"temperatures":temps,"disks":disk_data,"cooling":cooling(),
              "host":socket.gethostname(),"time":time.strftime("%Y-%m-%d %H:%M:%S"),"load":open("/proc/loadavg").read().split()[:3],
              "problems":pr,"cache_ts":d.get("ts"),"contour":contour_data,
              "daily_work":daily_work,"contour_total":contour_total,
              "system_status":sys_status,"today_truth":truth})
    d.update({"runtime":runtime,"runtime_age_sec":round(time.time()-RUNTIME.get("ts",0)) if RUNTIME.get("ts") else None})
    return d

def load_kiosk_page(name):
    with open(os.path.join(KIOSK_SOURCE_DIR,name),encoding="utf-8") as f:
        return f.read()

PAGE=load_kiosk_page("s13_kiosk_main.html")
TECH_PAGE=load_kiosk_page("s13_kiosk_tech.html")


class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path.startswith("/api/metrics"):
            with API_CACHE_LOCK:
                if API_CACHE["data"] is None or time.time()-API_CACHE["ts"]>=5:
                    started=time.monotonic(); API_CACHE["data"]=snapshot(); API_CACHE["data"]["kiosk_query_duration_ms"]=round((time.monotonic()-started)*1000); API_CACHE["ts"]=time.time()
                body=json.dumps(API_CACHE["data"]).encode()
            ct="application/json"
        elif self.path.startswith("/tech"): body=TECH_PAGE.encode(); ct="text/html; charset=utf-8"
        else: body=PAGE.encode(); ct="text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
if __name__=="__main__":
    threading.Thread(target=loop,daemon=True).start()
    threading.Thread(target=runtime_loop,daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1",8897),H).serve_forever()
