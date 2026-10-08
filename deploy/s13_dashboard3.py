#!/usr/bin/env python3
import json, re, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def sh(c,t=10):
    try: return subprocess.run(c,shell=True,capture_output=True,text=True,timeout=t).stdout.strip()
    except Exception: return ""
def pq(db,q,t=20):
    return sh("runuser -u postgres -- psql -d %s -At -F'|' -c \"%s\"" % (db,q),t)
def svc(n): return subprocess.run(["systemctl","is-active",n],capture_output=True,text=True).stdout.strip() or "?"
def rows(out):
    r=[]
    for l in out.splitlines():
        if "|" in l: r.append(l.split("|"))
    return r
def i(x):
    try: return int(str(x).strip())
    except Exception: return None

_lock=threading.Lock(); _prev={"t":None,"idle":0,"total":0}
def cpu_busy():
    p=[int(x) for x in open("/proc/stat").readline().split()[1:]]
    idle=p[3]+p[4]; tot=sum(p)
    with _lock: t0,i0,t0t=_prev["t"],_prev["idle"],_prev["total"]; _prev.update(t=time.time(),idle=idle,total=tot)
    if t0 is None: return 0
    dt=tot-t0t; di=idle-i0
    return int(100*(dt-di)/dt) if dt>0 else 0
def mem():
    d={}
    for l in open("/proc/meminfo"):
        k,v=l.split(":",1); d[k]=int(v.split()[0])
    tot=d["MemTotal"]/1048576; av=d["MemAvailable"]/1048576; st=d.get("SwapTotal",0)/1048576; sf=d.get("SwapFree",0)/1048576
    return {"pct":int((tot-av)/tot*100) if tot else 0,"used":round(tot-av,1),"total":round(tot,1),"swap":round(st-sf,1)}
def gpu():
    o=sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu,fan.speed --format=csv,noheader,nounits 2>/dev/null")
    if not o: return None
    try:
        u,mu,mt,pw,pl,gt,fn=[x.strip() for x in o.split(",")]
        return {"util":int(float(u)),"vram_used":int(float(mu)),"vram_total":int(float(mt)),"pct":int(float(mu)/float(mt)*100),"power":round(float(pw)),"temp":int(float(gt)),"fan":int(float(fn))}
    except Exception: return None
def temp_c():
    m=re.search(r"Package id 0:\s*\+([0-9.]+)",sh("sensors 2>/dev/null")); return int(float(m.group(1))) if m else 0
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
    flow={"received":rec,"category_today":i(cat),"category_total":i(cat_all),"medal_new":i(medal_new),"medal_changed":i(medal_ch),"queued_today":i(queued),"model_processed":i(model),
          "production":svc("crm-ai-assessment-runner.service"),"shadow":svc("crm-v3-shadow-predictor.service")}
    CACHE["data"]={"scope":scope,"medals":med,"queue":q,"admission":adm,"claimable":cl,"claimable_total":sum(x['count'] for x in cl),
                   "flow":flow,"heavy_ms":int((time.time()-t0)*1000),"ts":time.strftime('%H:%M:%S')}
    CACHE["ts"]=time.time()
def loop():
    while True:
        try: heavy()
        except Exception as e: CACHE["data"]={"err":str(e)}
        time.sleep(90)
def problems():
    d=CACHE["data"]; pr=[]; f=d.get("flow",{})
    if f.get("production")!="active": pr.append(["WARNING","Инференс продакшена ВЫКЛ","результаты модели не материализованы"])
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
    ref=rows.get("d24"); src="24h"
    if not ref:
        b=rows.get("baseline")
        if b and b.get("captured_at")!=latest.get("captured_at"): ref,src=b,"baseline"
    if ref:
        for k in ("processed_total","remaining_total","gold","silver","bronze","wood",
                  "deterministic_accept","no_commercial_entry","qwen_processed","document_completed_total"):
            if latest.get(k) is not None and ref.get(k) is not None: out["delta"][k]=latest[k]-ref[k]
        out["delta_source"]=src
    cats,d24=_contour_cats()
    for cc in cats:
        pv=d24.get(cc["category_code"])
        if pv and cc.get("coverage_pct") is not None and pv.get("coverage_pct") is not None:
            cc["coverage_delta_pp"]=round(cc["coverage_pct"]-pv["coverage_pct"],1)
    out["categories"]=cats
    return out

def snapshot():
    d=json.loads(json.dumps(CACHE["data"]))
    d.update({"cpu":cpu_busy(),"mem":mem(),"gpu":gpu(),"temp":temp_c(),"disks":disks(),"cooling":cooling(),
              "host":socket.gethostname(),"time":time.strftime("%Y-%m-%d %H:%M:%S"),"load":open("/proc/loadavg").read().split()[:3],
              "problems":problems(),"cache_ts":d.get("ts"),"contour":contour()})
    return d

PAGE=r"""<!doctype html><html><head><meta charset="utf-8"><title>S13 procurement</title><style>
*{box-sizing:border-box}body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;font-size:20px}
header{padding:10px 20px;background:#161b22;border-bottom:2px solid #30363d;display:flex;gap:24px;align-items:baseline}
h1{margin:0;font-size:24px;color:#58a6ff}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:14px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:12px 14px}
.card h2{margin:0 0 8px;font-size:16px;color:#8b949e;text-transform:uppercase;letter-spacing:1px}
.bar{height:20px;background:#21262d;border-radius:5px;overflow:hidden}.bar>span{display:block;height:100%}
.g{background:#2ea043}.y{background:#d29922}.r{background:#da3633}
.big{font-size:28px;font-weight:700}
.row{display:flex;justify-content:space-between;gap:10px;margin:3px 0}
.small{color:#8b949e;font-size:15px}
.chip{border:1px solid #30363d;border-radius:20px;padding:1px 8px;font-size:14px;margin:0 6px 6px 0;display:inline-block}
.dot{width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:6px}
.ok{background:#2ea043}.bad{background:#da3633}.warn{background:#d29922}
.flow div{padding:4px 0;border-bottom:1px solid #21262d;display:flex;justify-content:space-between}
.fans{display:flex;gap:20px;align-items:center;flex-wrap:wrap}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}.blades{width:48px;height:48px;animation:spin linear infinite}
</style></head><body>
<header><h1 id="host">S13</h1><div class="small" id="clock"></div><div class="small" id="cache"></div><div class="small" id="warn"></div></header>
<div class="grid">
 <div class="card" style="grid-column:span 4"><h2>АНАЛИТИЧЕСКИЙ КОНТУР <span id="cage" class="small"></span></h2><div id="contour"></div></div>
 <div class="card"><h2>CPU</h2><div class="big" id="cpu">-</div><div class="bar"><span id="cpub"></span></div><div class="small">нагрузка <span id="load"></span></div></div>
 <div class="card"><h2>ОЗУ</h2><div class="big" id="ram">-</div><div class="bar"><span id="ramb"></span></div><div class="small" id="ramt"></div></div>
 <div class="card"><h2>GPU</h2><div class="big" id="gpu">-</div><div class="bar"><span id="gpub"></span></div><div class="small" id="gput"></div></div>
 <div class="card"><h2>Диски</h2><div id="disks"></div></div>
 <div class="card" style="grid-column:span 2"><h2>ПОТОК ЗА СЕГОДНЯ (закупки)</h2><div id="flow" class="flow"></div></div>
 <div class="card" style="grid-column:span 2"><h2>ТЕКУЩЕЕ СОСТОЯНИЕ</h2><div id="current"></div></div>
 <div class="card" style="grid-column:span 2"><h2>ОЧЕРЕДЬ СЕЙЧАС</h2><div id="queue"></div></div>
 <div class="card" style="grid-column:span 2"><h2>Охлаждение</h2><div id="cool"></div></div>
 <div class="card" style="grid-column:span 4"><h2>ТЕКУЩИЕ ПРОБЛЕМЫ</h2><div id="problems"></div></div>
</div>
<script>
const $=i=>document.getElementById(i);const cls=p=>p>=85?'r':p>=70?'y':'g';const setb=(e,p)=>{e.className=cls(p);e.style.width=Math.min(100,p)+'%';};
const bc={GOLD:'#d4a017',SILVER:'#a8b3bd',BRONZE:'#b06a2b',WOOD:'#6e4b2a',UNSCORED:'#8b949e'};
const dur=v=>Math.max(0.15,2.1-1.9*Math.min(1,Math.max(0,v)));
const fanSvg=(d,c)=>`<svg class="blades" style="animation-duration:${d}s" viewBox="0 0 100 100"><g fill="${c}"><path d="M50 50 L49 6 A44 44 0 0 1 80 20 Z"/><path d="M50 50 L94 49 A44 44 0 0 1 80 80 Z" opacity=".85"/><path d="M50 50 L51 94 A44 44 0 0 1 20 80 Z"/><path d="M50 50 L6 51 A44 44 0 0 1 20 20 Z" opacity=".85"/></g><circle cx="50" cy="50" r="9" fill="#e6edf3"/></svg>`;
const chips=o=>Object.entries(o||{}).sort().map(([k,v])=>`<span class="chip"><b style="color:${bc[k]||'#8b949e'}">${k}</b> ${v}</span>`).join('');
async function tick(){try{const m=await (await fetch('/api/metrics')).json();
 $('host').textContent='S13: '+m.host;$('clock').textContent=m.time;$('cache').textContent='данные '+m.cache_ts;
 $('cpu').textContent=m.cpu+'%';setb($('cpub'),m.cpu);$('load').textContent=m.load.join(' ');
 $('ram').textContent=m.mem.pct+'%';setb($('ramb'),m.mem.pct);$('ramt').textContent=m.mem.used+'/'+m.mem.total+'G подкачка '+m.mem.swap+'G';
 if(m.gpu){$('gpu').textContent=m.gpu.util+'%';setb($('gpub'),m.gpu.util);$('gput').textContent=m.gpu.vram_used+'/'+m.gpu.vram_total+'MB '+m.gpu.power+'W '+m.gpu.temp+'C';}
 $('disks').innerHTML=(m.disks||[]).map(d=>`<div class="small"><b>${d.dev}</b> ${d.mount} ${d.pct!=null?d.pct+'%':''} ${d.temp?d.temp+'C':''} ${d.health}</div>`).join('');
 const ct=m.contour||{};
 if(ct.available&&ct.latest){const L=ct.latest,D=ct.delta||{},nn=v=>v==null?'-':Number(v).toLocaleString('ru-RU');
  const pct=L.eligible_total?Math.round(1000*L.processed_total/L.eligible_total)/10:0;
  const dd=k=>D[k]==null?'':` <span style="font-size:.6em;color:${D[k]>=0?'#2ea043':'#da3633'}">${D[k]>=0?'+':''}${D[k]}</span>`;
  const age=L.age_sec==null?null:Math.round(L.age_sec/60),fresh=age==null?'-':(L.age_sec>1800?'УСТАРЕЛО':age+' мин');
  const st=(t,v,s)=>`<div style="flex:1;min-width:190px"><div class="small">${t}</div><div class="big">${v}</div>${s||''}</div>`;
  const dtxt=(ct.delta_source==='24h')?'за 24ч':(ct.delta_source==='baseline'?'с baseline':'накопление');
  let h=`<div style="display:flex;gap:24px;flex-wrap:wrap">${st('ОБРАБОТАНО',nn(L.processed_total)+' / '+nn(L.eligible_total),'<div class="small">'+pct+'% '+dd('processed_total')+'</div>')}${st('ОСТАЛОСЬ',nn(L.remaining_total),'<div class="small">'+dtxt+' '+dd('remaining_total')+'</div>')}</div>`;
  h+=`<div class="bar" style="height:26px;margin:8px 0"><span class="g" style="width:${Math.min(100,pct)}%"></span></div>`;
  h+=`<div class="small">в работе ${nn(L.in_progress)} · перезапуск/ошибка ${nn(L.failed)} · заблок. ${nn(L.blocked)} · очередь drain ${nn(L.backlog_drain_remaining)}</div>`;
  h+=`<div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:6px">${st('ДЕТЕРМИН.',nn(L.deterministic_accept),'<div class="small">'+dd('deterministic_accept')+'</div>')}${st('НЕТ КОММЕРЦИИ',nn(L.no_commercial_entry),'<div class="small">'+dd('no_commercial_entry')+'</div>')}${st('QWEN',nn(L.qwen_processed),'<div class="small">'+dd('qwen_processed')+'</div>')}</div>`;
  h+=`<div class="small" style="margin-top:6px">МЕДАЛИ · GOLD ${nn(L.gold)}${dd('gold')} · SILVER ${nn(L.silver)}${dd('silver')} · BRONZE ${nn(L.bronze)}${dd('bronze')} · WOOD ${nn(L.wood)}${dd('wood')}</div>`;
  const cats=ct.categories||[];if(cats.length){h+='<div class="small" style="margin-top:6px">КАТЕГОРИИ · покрытие</div>'+cats.map(c=>`<div class="row small"><span>${c.category_code}</span><span>${nn(c.classified)}/${nn(c.total)} · ${c.coverage_pct==null?'-':c.coverage_pct+'%'}${c.coverage_delta_pp!=null?' <b style="color:#2ea043">'+c.coverage_delta_pp+'pp</b>':''}</span></div>`).join('');}
  h+=`<div class="small" style="margin-top:6px">ДОКУМЕНТЫ · в очереди ${nn(L.document_pending)} · в работе ${nn(L.document_processing)} · готово ${nn(L.document_completed_total)}${dd('document_completed_total')} · без связей ${nn(L.document_no_links)} · ошибок ${nn(L.document_failed)}</div>`;
  $('contour').innerHTML=h;$('cage').textContent='срез: '+fresh+(ct.delta_source==='24h'?' · Δ24ч':(ct.delta_source==='baseline'?' · с baseline':' · накопление'));
 }else{$('contour').innerHTML='<div class="small">нет снимков</div>';}
 const f=m.flow||{},r=f.received||{};
 $('flow').innerHTML=[['Получено новых',r.total],['  - 44-ФЗ',r.s44],['  - 223-ФЗ',r.s223],['Категория определена',f.category_today],['Обработано моделью',f.model_processed],['Медаль назначена',f.medal_new],['Медаль изменена',f.medal_changed],['В очередь',f.queued_today],['Перешло в розыгранные',r.awarded]].map(x=>`<div><span>${x[0]}</span><b>${x[1]==null?'...':x[1]}</b></div>`).join('')+`<div class="small">ПРОД ${f.production=='active'?'ON':'OFF'} | ТЕНЬ ${f.shadow=='active'?'ON':'OFF'}${f.production!='active'?' | ТОЛЬКО ТЕНЬ, РЕЗУЛЬТАТЫ НЕ МАТЕРИАЛИЗОВАНЫ':''}</div>`;
 const sc=m.scope||{},md=m.medals||{};
 const part=(name)=>`<div class="row"><b>${name}</b><span class="small">доп ${(sc[name]||{}).ELIGIBLE||0} · удерж ${(sc[name]||{}).HOLD||0} · искл ${(sc[name]||{}).EXCLUDED||0}</span></div>`+chips(md[name]||{});
 $('current').innerHTML='<div class="row"><b>ОТКРЫТО (торги)</b></div>'+part('OPEN')+'<div class="row" style="margin-top:8px"><b>РОЗЫГРАНО</b></div>'+part('AWARDED');
 const q=m.queue||{},a=m.admission||{};
 $('queue').innerHTML=`<div class="row"><span>В РАБОТЕ</span><b>${q.PROCESSING||0}</b></div><div class="row"><span>ОЖИДАЮТ: PENDING / PRE_RESEARCH</span><b>${q.PENDING||0} / ${q['PRE_RESEARCH_WAITING']||0}</b></div><div class="row"><span>НЕ ГОТОВЫ: HOLD / EXCLUDED</span><b>${a.HOLD||0} / ${a.EXCLUDED||0}</b></div><div class="row"><b>ДОСТУПНЫ СЕЙЧАС: ${m.claimable_total||0}</b></div>`+chips(Object.fromEntries((m.claimable||[]).map(c=>[c.band,c.count])));
 const fans=(m.cooling.fans||[]).map(x=>`<div style="text-align:center">${fanSvg(dur(x.rpm/3500).toFixed(2),'#58a6ff')}<div class="small">${x.rpm} RPM</div></div>`).join('');
 $('cool').innerHTML='<div class="fans">'+fans+(m.gpu&&m.gpu.fan!=null?`<div style="text-align:center">${fanSvg(dur(m.gpu.fan/100).toFixed(2),'#3fb950')}<div class="small">GPU ${m.gpu.fan}%</div></div>`:'')+`<span class="chip" style="color:#e6edf3">${m.temp}C CPU</span></div>`;
 $('problems').innerHTML=(m.problems||[]).map(p=>`<div style="padding:5px 10px;border-radius:8px;margin:3px 0;background:${p[0]=='CRITICAL'?'#3d1418':p[0]=='WARNING'?'#3d2f0f':'#12233d'}"><b style="color:${p[0]=='CRITICAL'?'#ff7b72':p[0]=='WARNING'?'#d29922':'#58a6ff'}">${p[0]}:</b> ${p[1]} <span class="small">${p[2]||''}</span></div>`).join('');
}catch(e){$('clock').textContent='ошибка '+e;}}
tick();setInterval(tick,3000);
</script></body></html>"""
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path.startswith("/api/metrics"): body=json.dumps(snapshot()).encode(); ct="application/json"
        else: body=PAGE.encode(); ct="text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
if __name__=="__main__":
    threading.Thread(target=loop,daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1",8897),H).serve_forever()
