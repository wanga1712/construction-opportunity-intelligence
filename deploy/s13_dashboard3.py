#!/usr/bin/env python3
# PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1
import json, os, re, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# System health probes — единый источник CPU/temp (read-only, без выдуманных нулей).
CRM_ROOT = "/opt/CRM_Streamlit"
if CRM_ROOT not in sys.path:
    sys.path.insert(0, CRM_ROOT)

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
RATE_WINDOW_MIN=60
ETA_OK_MAX_HOURS=12
ETA_EDGE_MAX_HOURS=24
ADMISSION_POLICY="BUSINESS_RESEARCH_ADMISSION_V2"
MAX_ROUTING_ATTEMPTS=int(os.environ.get("CRM_V3_ROUTING_MAX_ATTEMPTS","3"))

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
        qsql=("""
        SELECT count(DISTINCT procurement_id) FILTER (WHERE completed_at>=current_date),
               count(DISTINCT procurement_id) FILTER
                 (WHERE completed_at>=current_date-interval '1 day' AND completed_at<current_date),
               count(DISTINCT procurement_id) FILTER
                 (WHERE completed_at>=now()-interval '60 minutes')
          FROM document_processing_queue
         WHERE status='COMPLETED' AND pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
        """)
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
                      "errors":None,"no_links":None,"throughput_per_hour":None},
         "model":{"unit":"PROCUREMENT_X_CATEGORY","waiting":None,"working":None,
                  "raw_waiting_rows":None,"raw_working_rows":None,
                  "done_today":None,"raw_done_today":None,
                  "confirmed_today":None,"rejected_today":None,"unknown_today":None,
                  "throughput_per_hour":None},
         "commercial":{"objects":None,"with_commerce":None,"document_confirmed":None,
                       "category_opportunities":None,"result_today":None,
                       "result_yesterday":None,"open":{},"awarded":{}},
         "rates":{"arrivals_per_hour":None,"processed_per_hour":None}}
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
        cohort_sql="""
        WITH recv AS (
          SELECT id FROM crm_procurements WHERE crm_created_at>=current_date
        )
        SELECT count(*),
               count(*) FILTER (WHERE EXISTS (
                 SELECT 1 FROM crm_procurements p
                  WHERE p.id=recv.id AND p.ai_assessed_at>=current_date)),
               count(*) FILTER (WHERE EXISTS (
                 SELECT 1 FROM crm_procurement_category_opportunities o
                  WHERE o.procurement_id=recv.id AND o.status='CURRENT'
                    AND o.created_at>=current_date))
          FROM recv
        """
        cohort=rows(pq("crm",cohort_sql,30))
        if cohort:
            out["today"]["received"]=i(cohort[0][0])
            out["today"]["model_from_received"]=i(cohort[0][1])
            out["today"]["commercial_from_received"]=i(cohort[0][2])

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
        proc_sql="""
        SELECT count(DISTINCT procurement_id) FROM document_processing_queue
         WHERE status='COMPLETED' AND completed_at>=now()-interval '60 minutes'
           AND pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
        """
        pr=rows(pq("document_intelligence",proc_sql,20))
        p_n=i(pr[0][0]) if pr else None
        out["rates"]["processed_per_hour"]=float(p_n) if p_n else None

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
    # QUEUE NOW (distinct procurement_id)
    q={}
    for r in rows(pq("document_intelligence","SELECT status, count(DISTINCT procurement_id) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING') GROUP BY 1")):
        q[r[0]]=int(r[1])
    adm={}
    for r in rows(pq("document_intelligence","SELECT COALESCE(category_context->>'admission_state','-'), count(DISTINCT procurement_id) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING') GROUP BY 1")):
        adm[r[0]]=int(r[1])
    cl=[]
    for r in rows(pq("document_intelligence","SELECT COALESCE(research_prior_band,'UNSCORED'), count(DISTINCT procurement_id) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING') AND category_context->>'admission_state'='ELIGIBLE' GROUP BY 1 ORDER BY 1")):
        cl.append({"band":r[0],"count":int(r[1])})
    # FLOW TODAY
    slice_sql="SELECT count(*), count(*) FILTER (WHERE source_table='reestr_contract_44_fz'), count(*) FILTER (WHERE source_table='reestr_contract_223_fz'), count(*) FILTER (WHERE crm_stage='torgi'), count(*) FILTER (WHERE crm_stage='razygranye') FROM crm_procurements WHERE id > (SELECT max(id)-20000 FROM crm_procurements) AND crm_created_at >= current_date"
    rs=[x.strip() for x in pq("crm",slice_sql,30).split("|")]
    rec={"total":i(rs[0]),"s44":i(rs[1]),"s223":i(rs[2]),"torgi":i(rs[3]),"awarded":i(rs[4])}
    cat=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_procurement_category_opportunities WHERE created_at >= current_date",30)
    cat_all=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_procurement_category_opportunities",30)
    medal_ch=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_category_opportunity_medal_history WHERE evaluated_at >= current_date AND previous_effective_medal IS DISTINCT FROM new_effective_medal",30)
    medal_new=pq("crm","SELECT count(DISTINCT procurement_id) FROM crm_category_opportunity_medal_history WHERE evaluated_at >= current_date AND previous_effective_medal IS NULL AND new_effective_medal IS NOT NULL",30)
    queued=pq("document_intelligence","SELECT count(DISTINCT procurement_id) FROM document_processing_queue WHERE created_at >= current_date",30)
    model=pq("crm","SELECT count(DISTINCT id) FROM crm_procurements WHERE id > (SELECT max(id)-20000 FROM crm_procurements) AND ai_assessed_at >= current_date",30)
    # PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1: компактная read-only аналитика.
    # Тяжёлые all-time COUNT не делаем: validator — только за сегодня (29ms),
    # очередь/ошибки — по ограниченным выборкам.
    docstats={}
    for r in rows(pq("document_intelligence","SELECT status, count(*) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING') GROUP BY 1")):
        docstats[r[0]]=i(r[1])
    for r in rows(pq("document_intelligence","SELECT status, count(*) FROM document_processing_queue WHERE status IN ('COMPLETED','FAILED') AND completed_at >= current_date GROUP BY 1")):
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
    for r in rows(pq("document_intelligence","SELECT id, procurement_id, coalesce(last_error,'') FROM document_processing_queue WHERE status='FAILED' ORDER BY id DESC LIMIT 5")):
        errors.append({"id":i(r[0]),"pid":i(r[1]),"err":(r[2] or "")[:160]})
    cc=pq("crm","SELECT count(*), count(*) FILTER (WHERE confirmed_base_medal IS NOT NULL) FROM crm_procurement_category_opportunities WHERE status='CURRENT'")
    cat_conf=[i(x.strip()) for x in cc.split("|")] if "|" in cc else [None,None]
    prod_state=svc("crm-ai-assessment-runner.service")
    shadow_state=svc("crm-v3-shadow-predictor.service")
    flow={"received":rec,"category_today":i(cat),"category_total":i(cat_all),"medal_new":i(medal_new),"medal_changed":i(medal_ch),"queued_today":i(queued),"model_processed":i(model),
          "production":prod_state,"production_label":svc_label(prod_state),
          "shadow":shadow_state,"shadow_label":svc_label(shadow_state)}
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
def problems():
    d=CACHE["data"]; pr=[]; f=d.get("flow",{})
    if f.get("production")!="active":
        label=f.get("production_label") or svc_label(f.get("production"))
        pr.append(["WARNING",f"Инференс продакшена: {label}",
                   "production assessments сейчас не материализуются"])
    if f.get("category_today")==0: pr.append(["WARNING","Сегодня нет материализованных категорий","0 возможностей создано сегодня"])
    if f.get("received",{}) and f["received"].get("total")==0: pr.append(["CRITICAL","Сегодня нет новых закупок","остановился приём?"])
    pr.append(["INFO","Доступно в очереди: %s" % d.get("claimable_total",0),"только eligible"])
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
    day_start=(contour_data or {}).get("day_start") or {}
    backlog_at_start=day_start.get("remaining_total")
    admitted_today=today.get("admitted")
    processed=today.get("processed")
    daily_workload=(backlog_at_start+admitted_today
                    if backlog_at_start is not None and admitted_today is not None else None)
    daily_remaining=(daily_workload-processed
                     if daily_workload is not None and processed is not None else None)
    daily_pct=(round(100.0*processed/daily_workload,1)
               if daily_workload not in (None,0) and processed is not None else None)
    current_remaining=latest.get("remaining_total")
    backlog_delta=(current_remaining-backlog_at_start
                   if current_remaining is not None and backlog_at_start is not None else None)
    eligible=latest.get("eligible_total")
    processed_total=latest.get("processed_total")
    contour_pct=(round(1000.0*processed_total/eligible)/10
                 if eligible and processed_total is not None else None)
    daily_work={
        "received_today":today.get("received"),
        "admitted_today":admitted_today,
        "backlog_at_day_start":backlog_at_start,
        "backlog_at_day_start_captured_at":day_start.get("captured_at"),
        "backlog_at_day_start_source":day_start.get("source"),
        "daily_workload":daily_workload,
        "processed_from_day_work_set":processed,
        "remaining_from_day_work_set":daily_remaining,
        "daily_progress_pct":daily_pct,
        "current_remaining":current_remaining,
        "backlog_delta_today":backlog_delta,
        "previous_day":{
            "received":yesterday.get("received"),
            "admitted":yesterday.get("admitted"),
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

def snapshot():
    d=json.loads(json.dumps(CACHE["data"]))
    cpu=cpu_metrics()
    temps=temperatures()
    gpu_data=gpu()
    disk_data=disks()
    pr=problems()
    contour_data=contour()
    daily_work,contour_total=daily_work_contract(d.get("command") or {},contour_data)
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
              "system_status":sys_status})
    return d

PAGE=r"""<!doctype html><html><head><meta charset="utf-8"><title>S13 procurement</title><style>
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;font-size:16px;overflow:hidden}
header{height:42px;padding:6px 14px;background:#161b22;border-bottom:2px solid #30363d;display:flex;gap:18px;align-items:center}
.brand{margin:0;font-size:22px;color:#58a6ff;font-weight:700}.header-right{margin-left:auto;display:flex;gap:18px;align-items:center}
.system{padding:3px 10px;border-radius:14px;font-weight:700;border:1px solid #30363d}
.sys-ok{color:#3fb950;background:#0d2818}.sys-warn{color:#d29922;background:#2d220b}.sys-bad{color:#ff7b72;background:#3d1418}.sys-unknown{color:#8b949e;background:#21262d}
.grid{height:calc(100vh - 42px);display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-template-rows:190px minmax(0,1fr) 60px 230px 80px;gap:8px;padding:8px}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:5px 8px;min-width:0}
.span4{grid-column:span 4}.span2{grid-column:span 2}.card h2{margin:0 0 4px;font-size:13px;color:#8b949e;text-transform:uppercase;letter-spacing:1px}
.topcmd{display:grid;grid-template-columns:minmax(0,2.35fr) minmax(360px,.9fr);gap:10px;height:100%}.topsec{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:7px 9px;min-width:0;overflow:hidden}
.topsec h2{color:#58a6ff}.tech-link{color:#58a6ff;text-decoration:none;border:1px solid #30363d;border-radius:6px;padding:2px 8px;font-size:13px}
.card h2.sub{margin-top:7px;color:#58a6ff}.bar{height:14px;background:#21262d;border-radius:5px;overflow:hidden}.bar>span{display:block;height:100%}
.g{background:#2ea043}.y{background:#d29922}.r{background:#da3633}.big{font-size:22px;font-weight:700}.row{display:flex;justify-content:space-between;gap:10px;margin:3px 0}
.small{color:#8b949e;font-size:13px}.tiny{color:#8b949e;font-size:11px}.chip{border:1px solid #30363d;border-radius:20px;padding:1px 8px;font-size:13px;margin:0 5px 5px 0;display:inline-block}
.funnel{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;align-items:stretch;height:calc(100% - 22px)}.stage{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px;min-height:0;display:flex;flex-direction:column;justify-content:center}
.stage .label{font-size:12px;color:#8b949e;text-transform:uppercase}.stage .value{font-size:30px;font-weight:750;line-height:1.1}.stage .unit{font-size:12px;color:#8b949e}.arrow{text-align:center;color:#58a6ff;font-size:28px}
.delta-up{color:#3fb950}.delta-down{color:#ff7b72}.split-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.inner-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.metric-pair{display:flex;justify-content:space-between;border-bottom:1px solid #21262d;padding:2px 0;line-height:1.22}.medals{display:flex;gap:8px;flex-wrap:wrap}.medal{font-weight:700}.flow-line{display:flex;gap:24px;align-items:baseline}.flow-state-ok{color:#3fb950}.flow-state-warn{color:#d29922}.flow-state-bad{color:#ff7b72}.flow-state-unknown{color:#8b949e}
.resources{display:grid;grid-template-columns:2.1fr 2.1fr 1.2fr 1.3fr;gap:8px;height:calc(100% - 20px)}.resbox{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:7px 9px;min-height:0;overflow:hidden}.activity-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}.activity{background:#161b22;border:1px solid #30363d;border-radius:7px;padding:4px 6px;min-height:0}.activity b{display:block;font-size:20px;line-height:1.05}.activity span{font-size:10px;line-height:1.1;color:#8b949e}
.daily-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:5px}.daily-kpi{background:#161b22;border:1px solid #30363d;border-radius:7px;padding:4px 7px;min-width:0}.daily-kpi .label{font-size:10px;color:#8b949e;text-transform:uppercase;white-space:nowrap}.daily-kpi .value{font-size:23px;font-weight:750;line-height:1.08}.daily-kpi .note{font-size:10px;color:#8b949e;white-space:nowrap}
.daily-progress{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;margin-top:6px;align-items:end}.daily-progress .track{height:19px;background:#21262d;border-radius:5px;overflow:hidden}.daily-progress .track>span{display:block;height:100%;background:#2ea043}.daily-progress .pct{font-size:27px;font-weight:750;line-height:1}.daily-meta{display:flex;justify-content:space-between;gap:12px;margin-top:3px}.daily-tail{font-weight:700}.daily-tail-ok{color:#3fb950}.daily-tail-warn{color:#d29922}.contour-note{margin-top:4px;color:#8b949e;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.resbox h3{margin:0 0 4px;font-size:13px;color:#58a6ff}.cores{display:grid;grid-template-columns:repeat(8,1fr);gap:2px;margin-top:4px}.core{height:12px;background:#21262d;border-radius:2px;overflow:hidden;position:relative}
.core>span{display:block;position:absolute;bottom:0;width:100%}.core>i{position:absolute;top:0;left:1px;font-style:normal;font-size:9px;color:#8b949e}.temp{padding:1px 7px;border-radius:6px;display:inline-block}
.status-ok{color:#3fb950}.status-warn{color:#d29922}.status-bad{color:#ff7b72}.status-unknown{color:#8b949e}.fans{display:flex;gap:12px;align-items:center}.blades{width:32px;height:32px;animation:spin linear infinite}
.problems-card{min-height:0;overflow:hidden}.problem{padding:4px 9px;border-radius:6px;margin:3px 0;font-size:14px}.problem-critical{background:#3d1418}.problem-warning{background:#2d220b}.problem-info{background:#12233d}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
</style></head><body>
<header><div class="brand">S13 • АНАЛИТИЧЕСКИЙ КОНТУР</div><div class="header-right"><a class="tech-link" href="/tech">TECH</a><div id="clock" class="small"></div><div id="cache" class="small"></div><div id="system" class="system sys-unknown">СОСТОЯНИЕ НЕ ОПРЕДЕЛЕНО</div></div></header>
<div class="grid">
 <div class="card span4"><div class="topcmd"><div class="topsec"><h2>СЕГОДНЯШНИЙ ПОТОК <span class="tiny">все значения — закупки</span></h2><div id="daily_work"></div></div><div class="topsec"><h2>АКТИВНОСТЬ ЗА СЕГОДНЯ</h2><div id="activity" class="activity-grid"></div></div></div></div>
 <div class="card span2"><h2>ОЧЕРЕДЬ ОБРАБОТКИ · ЗАДАЧИ</h2><div id="docpipe"></div><h2 class="sub">МОДЕЛЬ · КАНДИДАТЫ</h2><div id="modelpipe"></div></div>
 <div class="card span2"><h2>LIVE COMMERCIAL · OPEN + AWARDED</h2><div id="commercial"></div></div>
 <div class="card span4"><h2>СОСТОЯНИЕ ПОТОКА</h2><div id="flowstate"></div></div>
 <div class="card span4"><h2>РЕСУРСЫ S13 <span id="load" class="small"></span></h2><div class="resources">
  <div class="resbox"><h3>CPU <span id="cput" class="small"></span></h3><div class="big" id="cpu">-</div><div class="bar"><span id="cpub"></span></div><div class="small" id="cpu_cap"></div><div class="small" id="cpu_freq"></div><div class="cores" id="cores"></div></div>
  <div class="resbox"><h3>GPU</h3><div class="big" id="gpu">-</div><div class="bar"><span id="gpub"></span></div><div class="small" id="gpu_power"></div><div class="small" id="gpu_cap"></div><div class="small" id="gpu_state"></div><div class="small" id="gput"></div></div>
  <div class="resbox"><h3>ПАМЯТЬ / НАГРУЗКА</h3><div class="big" id="ram">-</div><div class="bar"><span id="ramb"></span></div><div class="small" id="ramt"></div><div class="small" id="coresum"></div><div class="small" id="temp"></div><div class="small" id="tempsrc"></div></div>
  <div class="resbox"><h3>ДИСКИ / ОХЛАЖДЕНИЕ</h3><div id="disks"></div><div id="cool"></div></div>
 </div></div>
 <div class="card span4 problems-card"><h2>ПРОБЛЕМЫ</h2><div id="problems"></div></div>
</div>
<script>
const $=i=>document.getElementById(i),cls=p=>p>=85?'r':p>=70?'y':'g';
const setb=(e,p)=>{e.className=p==null?'':cls(p);e.style.width=p==null?'0':Math.min(100,p)+'%';};
const nn=v=>v==null?'н/д':Number(v).toLocaleString('ru-RU');
const num1=v=>v==null?'н/д':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:1});
const line=(a,b)=>`<div class="metric-pair"><span>${a}</span><b>${b}</b></div>`;
const sumMedals=o=>['GOLD','SILVER','BRONZE','WOOD','UNSCORED'].reduce((n,k)=>n+Number((o||{})[k]||0),0);
const delta=(v,unit='')=>v==null?'':` <span class="${v>=0?'delta-up':'delta-down'}">${v>=0?'↑':'↓'}${nn(Math.abs(v))}${unit}</span>`;
const dur=v=>Math.max(.15,2.1-1.9*Math.min(1,Math.max(0,v)));
const fanSvg=(d,c)=>`<svg class="blades" style="animation-duration:${d}s" viewBox="0 0 100 100"><g fill="${c}"><path d="M50 50 L49 6 A44 44 0 0 1 80 20 Z"/><path d="M50 50 L94 49 A44 44 0 0 1 80 80 Z"/><path d="M50 50 L51 94 A44 44 0 0 1 20 80 Z"/><path d="M50 50 L6 51 A44 44 0 0 1 20 20 Z"/></g><circle cx="50" cy="50" r="9" fill="#e6edf3"/></svg>`;
const medal=(name,obj)=>{const colors={GOLD:'#d4a017',SILVER:'#a8b3bd',BRONZE:'#b06a2b',WOOD:'#6e4b2a',UNSCORED:'#8b949e'};return Object.entries(obj||{}).sort((a,b)=>['GOLD','SILVER','BRONZE','WOOD','UNSCORED'].indexOf(a[0])-['GOLD','SILVER','BRONZE','WOOD','UNSCORED'].indexOf(b[0])).map(([k,v])=>`<span class="medal" style="color:${colors[k]}">${k} ${nn(v)}</span>`).join(' · ');};
const fmtEta=h=>h==null?'н/д':(h<1?Math.max(1,Math.round(h*60))+' мин':Math.floor(h)+' ч '+Math.round((h-Math.floor(h))*60)+' мин');
async function tick(){try{const m=await (await fetch('/api/metrics')).json(),cmd=m.command||{},t=cmd.today||{},d=cmd.documents||{},mo=cmd.model||{},co=cmd.commercial||{},rates=cmd.rates||{},ct=m.contour||{},dw=m.daily_work||{},ctTotal=m.contour_total||{},prev=dw.previous_day||{},dk=m.daily||{};
 $('clock').textContent=m.time||'';$('cache').textContent='данные '+(m.cache_ts||'н/д');
 const ss=m.system_status||{state:'UNKNOWN',label:'СОСТОЯНИЕ НЕ ОПРЕДЕЛЕНО'};$('system').textContent=(ss.state==='OK'?'● ':ss.state==='WARNING'?'⚠ ':ss.state==='CRITICAL'?'✕ ':'? ')+ss.label;$('system').className='system '+(ss.state==='OK'?'sys-ok':ss.state==='WARNING'?'sys-warn':ss.state==='CRITICAL'?'sys-bad':'sys-unknown');
 const dt=dk.today||{},age=ctTotal.snapshot_age_sec==null?null:Math.round(ctTotal.snapshot_age_sec/60),dailyPct=dw.daily_progress_pct,barWidth=dailyPct==null?0:Math.max(0,Math.min(100,dailyPct)),tail=dw.backlog_delta_today,tailText=tail==null?'н/д':(tail>0?'+':'')+nn(tail)+' '+(tail>0?'⚠ растёт':tail<0?'✓ сокращается':'без изменений'),tailCls=tail==null?'':tail>0?'daily-tail-warn':'daily-tail-ok';
 const metric=(label,value,note)=>`<div class="daily-kpi"><div class="label">${label}</div><div class="value">${nn(value)}</div><div class="note">${note||''}</div></div>`;
 $('daily_work').innerHTML=`<div class="daily-kpis">${metric('Пришло',dw.received_today,delta(dw.received_today-prev.received||0))}${metric('Допущено в работу',dw.admitted_today,delta(dw.admitted_today-prev.admitted||0))}${metric('Остаток с вчера',dw.backlog_at_day_start,'день начинается здесь')}${metric('Всего к обработке',dw.daily_workload,'вчерашний хвост + новые')}${metric('Обработано',dw.processed_from_day_work_set,delta(dw.processed_from_day_work_set-prev.processed||0))}${metric('Осталось',dw.remaining_from_day_work_set,'из рабочего объёма дня')}</div><div class="daily-progress"><div><div class="track"><span style="width:${barWidth}%"></span></div><div class="daily-meta"><span class="small">Прогресс сегодняшнего объёма</span><span class="daily-tail ${tailCls}">Хвост с начала дня: ${tailText}</span></div></div><div class="pct">${dailyPct==null?'н/д':num1(dailyPct)+'%'}</div></div><div class="contour-note">Общий накопленный контур: ${nn(ctTotal.processed_total)} / ${nn(ctTotal.eligible_total)} · ${ctTotal.progress_pct==null?'н/д':num1(ctTotal.progress_pct)+'%'} · осталось ${nn(ctTotal.remaining_total)} · срез ${age==null?'н/д':age+' мин'} · ${ct.delta_source||'н/д'}</div>`;
 const acts=[['Задачи документов завершены',dt.processed,'procurements'],['AI assessed',t.model_processed,'procurements'],['Validated match details',mo.raw_done_today,'match details'],['Commercial results',co.result_today,'procurements']];
 $('activity').innerHTML=acts.map(a=>`<div class="activity"><b>${nn(a[1])}</b><span>${a[0]} · ${a[2]}</span></div>`).join('');
 const docRate=d.throughput_per_hour,docEta=(docRate>0&&d.waiting>0)?d.waiting/docRate:null;
 $('docpipe').innerHTML=`<div class="tiny">1 задача = 1 procurement queue job; не физический документ</div>`+line('Задач ожидают',nn(d.waiting))+line('Задач в работе',nn(d.working))+line('Задач готово сегодня',nn(d.done_today))+line('Ошибок в backlog',nn(d.errors))+line('Скорость',docRate==null?'н/д':num1(docRate)+' задач/час')+line('Хвост',fmtEta(docEta))+`<div class="tiny">throughput: последние 30 завершённых задач</div>`;
 $('modelpipe').innerHTML=`<div class="tiny">кандидатов (procurement × category) · current opportunities ${nn(mo.current_opportunity_pairs)}</div>`+line('Кандидатов ожидают',nn(mo.waiting))+line('Сейчас в работе',nn(mo.working))+line('Проверено сегодня',nn(mo.done_today))+line('Подтверждено сегодня',nn(mo.confirmed_today))+line('Отклонено сегодня',nn(mo.rejected_today))+line('Не определено сегодня',nn(mo.unknown_today))+line('Скорость',mo.throughput_per_hour==null?'н/д':num1(mo.throughput_per_hour)+' кандидатов/час')+`<div class="tiny">source=RESEARCHABLE · GOODS only · raw backlog → <a class="tech-link" href="/tech">TECH</a></div>`;
 const aw=dk.awarded_today||{};
 const live=co.live_total,excluded=co.excluded_count,excludedLink=excluded?` · вне live cohort ${nn(excluded)} → <a class="tech-link" href="/tech">TECH</a>`:'';
 $('commercial').innerHTML=`<div class="inner-grid"><div>${line('LIVE COMMERCIAL',nn(live))}${line('Документально подтверждено',nn(co.document_confirmed_live))}${line('Категорийные возможности',nn(co.category_opportunities_live))}</div><div>${line('Идут торги',nn(sumMedals(co.open)))}${line('Разыгранные',nn(sumMedals(co.awarded)))}<div class="tiny">CURRENT + ELIGIBLE + OPEN/AWARDED</div></div></div><div class="split-grid"><div><div class="small">ИДУТ ТОРГИ</div><div class="medals">${medal('OPEN',co.open)}</div></div><div><div class="small">РАЗЫГРАННЫЕ</div><div class="medals">${medal('AWARDED',co.awarded)}</div></div></div><div class="tiny">${excludedLink} · medal invariant ${co.medal_invariant_ok?'OK':'FAIL'} · сегодня разыграно: direct ${nn(aw.direct||0)} / объекты ${nn(aw.object||0)}</div>`;
 const arrive=rates.arrivals_per_hour,proc=rates.processed_per_hour,balance=(arrive!=null&&proc!=null)?arrive-proc:null,qchg=(ct.delta_1h||{}).remaining_total;
 let fs='СКОРОСТЬ ПОКА НЕ ОПРЕДЕЛЕНА',fcls='flow-state-unknown';
 if(arrive!=null&&proc!=null){if(qchg!=null&&qchg>0&&balance>0){fs='⚠ ОЧЕРЕДЬ РАСТЁТ';fcls='flow-state-warn';}else if(qchg!=null&&qchg<0){fs='● ПОТОК СТАБИЛЕН · ОЧЕРЕДЬ СОКРАЩАЕТСЯ';fcls='flow-state-ok';}else{fs=balance>0?'⚠ ПРИТОК ВЫШЕ ОБРАБОТКИ':'● ПОТОК СТАБИЛЕН';fcls=balance>0?'flow-state-warn':'flow-state-ok';}}
 $('flowstate').innerHTML=`<div class="flow-line"><b class="${fcls}" style="font-size:20px">${fs}</b><span>приходит: <b>${arrive==null?'н/д':num1(arrive)+'/час'}</b></span><span>обрабатываем: <b>${proc==null?'н/д':num1(proc)+'/час'}</b></span><span>баланс: <b>${balance==null?'н/д':(balance>0?'+':'')+num1(balance)+'/час'}</b></span><span>очередь за час: <b>${qchg==null?'н/д':(qchg>0?'+':'')+num1(qchg)}</b></span></div>`;
 const cv=m.cpu_detail||{},cap=cv.cap||{},cp=cv.busy_pct??cv.total,per=cv.per||[],g=m.gpu,tp=m.temperatures||{},tempC=tp.display;
 $('cpu').textContent=cp==null?'н/д':num1(cp)+'% busy';setb($('cpub'),cp);
 $('cput').textContent=cv.status&&cv.status!=='OK'?'('+cv.status+')':'';
 $('cpu_cap').innerHTML=`CAP ${cap.cap_pct==null?'н/д':cap.cap_pct+'%'} · ~${cv.approx_hw_pct==null?'н/д':num1(cv.approx_hw_pct)+'% hw-equiv'} · свободно внутри cap ${cv.free_inside_cap_pct==null?'н/д':num1(cv.free_inside_cap_pct)+'%'}`;
 $('cpu_freq').textContent=`${cap.cur_mhz==null?'н/д':cap.cur_mhz.toFixed(2)+' GHz'} / ${cap.scaling_max_mhz==null?'н/д':cap.scaling_max_mhz.toFixed(2)+' GHz'} · turbo ${cap.no_turbo===false?'ON':cap.no_turbo===true?'OFF':'н/д'} · ${cap.governor||'governor н/д'}`;
 $('coresum').textContent=per.length?`ядра ${Math.min(...per).toFixed(1)}…${Math.max(...per).toFixed(1)}% · ${per.length}`:'ядра н/д';
 $('cores').innerHTML=per.map((v,n)=>`<div class="core" title="core ${n}: ${v}%"><span class="${cls(v)}" style="height:${Math.min(100,v)}%"></span><i>${n}</i></div>`).join('');
 $('load').textContent='нагрузка '+(m.load||[]).join(' ');
 $('temp').innerHTML=tempC==null?'CPU temp н/д':`CPU <span class="temp" style="background:${tp.status==='CRITICAL'?'#3d1418':tp.status==='WARNING'?'#2d220b':'#12233d'}">${tempC}°C ✓</span>`;
 $('tempsrc').textContent='temp: '+(tp.source||'н/д')+' · '+(tp.status||'UNKNOWN');
 $('ram').textContent=m.mem.pct+'%';setb($('ramb'),m.mem.pct);$('ramt').textContent=`${m.mem.used}/${m.mem.total} GB · swap ${m.mem.swap} GB`;
 if(g){$('gpu').textContent=g.util==null?'н/д':num1(g.util)+'% busy';setb($('gpub'),g.util);$('gpu_power').textContent=`draw ${g.power==null?'н/д':g.power+' W'} / cap ${g.limit==null?'н/д':g.limit+' W'} · до cap ${g.headroom_w==null?'н/д':g.headroom_w+' W'}`;$('gpu_cap').textContent=`default ${g.default_limit==null?'н/д':g.default_limit+' W'} · cap ${g.power_cap_pct==null?'н/д':g.power_cap_pct+'%'} · locked ${g.locked_w==null?'н/д':g.locked_w+' W'}`;$('gpu_state').innerHTML=`<span class="${g.power_state==='POWER_LIMIT'?'status-warn':'status-ok'}">${g.power_state==='POWER_LIMIT'?'POWER LIMIT':g.power_state==='NEAR_POWER_CAP'?'БЛИЗКО К POWER CAP':'НЕ УПИРАЕТСЯ В CAP'}</span>${g.throttle_reasons&&g.throttle_reasons.length?' · '+g.throttle_reasons.join(', '):''}`;$('gput').textContent=`VRAM ${g.vram_used==null?'н/д':(g.vram_used/1024).toFixed(1)+'/'+(g.vram_total/1024).toFixed(1)+' GB'} · ${g.temp==null?'н/д':g.temp+'°C'}`;}else{$('gpu').textContent='н/д';setb($('gpub'),null);$('gpu_power').textContent='GPU данные н/д';$('gpu_cap').textContent='';$('gpu_state').textContent='';$('gput').textContent='';}
 $('disks').innerHTML=(m.disks||[]).map(x=>`<div class="small"><b>${x.dev}</b> ${x.mount} ${x.pct==null?'н/д':x.pct+'%'} ${x.temp?x.temp+'C':''} ${x.health}</div>`).join('');
 const fans=(m.cooling&&m.cooling.fans||[]).map(x=>`<span class="small">${x.rpm} RPM</span>`).join(' · ');$('cool').innerHTML=`<div class="small" style="margin-top:4px">FAN ${fans||'н/д'}${g&&g.fan!=null?' · GPU '+g.fan+'%':''}</div>`;
 $('problems').innerHTML=(m.problems||[]).length?(m.problems||[]).slice(0,3).map(p=>`<div class="problem problem-${String(p[0]||'INFO').toLowerCase()}"><b>${p[0]}:</b> ${p[1]} <span class="tiny">${p[2]||''}</span></div>`).join(''):'<div class="status-ok">✓ ПРОБЛЕМ НЕТ</div>';
}catch(e){$('clock').textContent='ошибка '+e;}}
tick();setInterval(tick,3000);
</script></body></html>"""

TECH_PAGE=r"""<!doctype html><html><head><meta charset="utf-8"><title>S13 TECH</title><style>
body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;font-size:15px;padding:18px}
h1{color:#58a6ff;margin:0 0 8px}.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px;margin:10px 0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #30363d}th{color:#8b949e}
.small{color:#8b949e}a{color:#58a6ff}
</style></head><body><h1>S13 · TECH / metric semantics</h1><div><a href="/">← Command Center</a></div><div class="card"><h2>Model candidate pool diagnostics</h2><div class="small">Сырой validator backlog не является бизнес-счётом киоска.</div><p id="modelpool"></p></div><div class="card"><h2>Current opportunities вне live cohort</h2><div class="small">CURRENT opportunity, но не CURRENT + ELIGIBLE + OPEN/AWARDED. В main totals не входят.</div><table><thead><tr><th>source_lifecycle</th><th>admission_state</th><th>commercial_state</th><th>opportunity_track</th><th>procurements</th></tr></thead><tbody id="excluded"></tbody></table><p id="total"></p></div>
<script>
const $=i=>document.getElementById(i);
async function tick(){const m=await (await fetch('/api/metrics')).json(),cmd=m.command||{},c=cmd.commercial||{},mo=cmd.model||{},rows=c.excluded_breakdown||[];
$('modelpool').textContent=`CURRENT_OPPORTUNITY_PAIRS=${mo.current_opportunity_pairs??'н/д'} · CANDIDATE_POOL_PAIRS=${mo.waiting??'н/д'} · COMMERCIAL_STATES=${(mo.commercial_states||[]).join(',')} · SOURCE_FILTER=${mo.source_filter??'н/д'} · GOODS_ONLY=${mo.goods_only?'YES':'NO'} · RAW_PENDING_MATCH_DETAILS=${mo.raw_waiting_rows??'н/д'} · RAW_WORKING=${mo.raw_working_rows??'н/д'} · WORKING_PAIRS=${mo.working??'н/д'}`;
$('excluded').innerHTML=rows.map(r=>`<tr><td>${r.source_lifecycle}</td><td>${r.admission_state}</td><td>${r.commercial_state}</td><td>${r.opportunity_track}</td><td>${r.procurements}</td></tr>`).join('');
$('total').textContent=`UNEXPLAINED_ACTIVE=${c.excluded_count??'н/д'} · LIVE_COMMERCIAL=${c.live_total??'н/д'} · MEDAL_INVARIANT=${c.medal_invariant_ok?'OK':'FAIL'}`;}
tick();setInterval(tick,10000);
</script></body></html>"""
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path.startswith("/api/metrics"): body=json.dumps(snapshot()).encode(); ct="application/json"
        elif self.path.startswith("/tech"): body=TECH_PAGE.encode(); ct="text/html; charset=utf-8"
        else: body=PAGE.encode(); ct="text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
if __name__=="__main__":
    threading.Thread(target=loop,daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1",8897),H).serve_forever()
