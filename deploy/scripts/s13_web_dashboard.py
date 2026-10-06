#!/usr/bin/env python3
"""S13 web dashboard: JSON metrics + a self-contained graphical HTML page."""
import json, os, subprocess, threading, time, socket, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
_prev = {"t": None, "idle": 0, "total": 0}
_hist = {"cpu": [], "gpu": []}

def sh(cmd, timeout=6):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""

def cpu_busy():
    with open("/proc/stat") as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    idle = parts[3] + parts[4]; total = sum(parts)
    with _lock:
        t0, i0, tot0 = _prev["t"], _prev["idle"], _prev["total"]
        _prev.update(t=tm, idle=idle, total=total) if False else None
        tm = time.time(); _prev.update(t=tm, idle=idle, total=total)
    if t0 is None:
        return 0
    dt = total - tot0; di = idle - i0
    return int(100 * (dt - di) / dt) if dt > 0 else 0

def mem():
    d = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1); d[k] = int(v.split()[0])
    tot = d["MemTotal"]/1048576; avail = d["MemAvailable"]/1048576
    st = d.get("SwapTotal",0)/1048576; sf = d.get("SwapFree",0)/1048576
    return {"total":round(tot,1),"used":round(tot-avail,1),"avail":round(avail,1),
            "pct":int((tot-avail)/tot*100) if tot else 0,
            "swap_total":round(st,1),"swap_used":round(st-sf,1),
            "swap_pct":int((st-sf)/st*100) if st else 0}

def temp_c():
    out = sh("sensors 2>/dev/null")
    m = re.search(r"Package id 0:\s*\+([0-9.]+)", out)
    return int(float(m.group(1))) if m else 0

def gpu():
    out = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu,fan.speed --format=csv,noheader,nounits 2>/dev/null")
    if not out: return None
    try:
        u,mu,mt,pw,pl,gt,fan = [x.strip() for x in out.split(",")]
        return {"util":int(float(u)),"vram_used":int(float(mu)),"vram_total":int(float(mt)),
                "vram_pct":int(float(mu)/float(mt)*100),"power":round(float(pw)),"limit":round(float(pl)),"temp":int(float(gt)),"fan":int(float(fan))}
    except Exception:
        return None

def disks():
    res = []
    mounts = {"/": "sda", "/data": "sdc"}
    models = {}
    for line in sh("lsblk -o NAME,SIZE,MODEL -dn").splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0] in ("sda", "sdb", "sdc"):
            models[parts[0]] = parts[2].strip() if len(parts) == 3 else ""
    for dev in ("sda", "sdb", "sdc"):
        d = {"dev": dev, "model": models.get(dev, ""), "mount": None}
        for m, dv in mounts.items():
            if dv == dev:
                d["mount"] = m
        if d["mount"]:
            out = sh("df -h " + d["mount"] + " 2>/dev/null | awk \'NR==2{gsub(\"%\",\"\",$5);print $2\"|\"$3\"|\"$4\"|\"$5}\'")
            if "|" in out:
                sz, us, av, pc = out.split("|")
                d.update(size=sz, used=us, avail=av, pct=int(pc))
        sm = sh("smartctl -H -A /dev/%s 2>/dev/null" % dev)
        d["health"] = "PASSED" if "PASSED" in sm else ("FAILED" if "FAILED" in sm else "n/a")
        m = re.search(r"Temperature_Celsius.*?-\s*(\d+)", sm)
        d["temp"] = int(m.group(1)) if m else None
        m = re.search(r"Current_Pending_Sector.*?-\s*(\d+)", sm)
        d["pending"] = int(m.group(1)) if m else None
        m = re.search(r"Reallocated_Sector_Ct.*?-\s*(\d+)", sm)
        d["realloc"] = int(m.group(1)) if m else None
        res.append(d)
    return res

def svc(name):
    return subprocess.run(["systemctl","is-active",name],capture_output=True,text=True).stdout.strip() or "unknown"

def services():
    names={"crm-streamlit":"CRM UI","ollama":"Ollama","postgresql@17-main":"PostgreSQL",
           "crm-system-health-collector":"Health collector","tender-docs-band-gold-1":"docs GOLD-1",
           "tender-docs-band-gold-2":"docs GOLD-2","tender-docs-band-silver":"docs SILVER",
           "tender-docs-band-bronze":"docs BRONZE","tender-docs-band-wood":"docs WOOD/UNSC"}
    return [{"id":k,"label":v,"state":svc(k)} for k,v in names.items()]

def cooling():
    out = sh("sensors 2>/dev/null")
    temps = []
    m = re.search(r"Package id 0:\s*\+([0-9.]+)", out)
    if m: temps.append({"label":"CPU package","c":int(float(m.group(1)))})
    cores = [float(x) for x in re.findall(r"Core \d+:\s*\+([0-9.]+)", out)]
    if cores: temps.append({"label":"CPU cores max","c":int(max(cores))})
    m = re.search(r"SYSTIN:\s*\+([0-9.]+)", out)
    if m: temps.append({"label":"Motherboard","c":int(float(m.group(1)))})
    m = re.search(r"PECI Agent 0:\s*\+([0-9.]+)", out)
    if m: temps.append({"label":"CPU PECI","c":int(float(m.group(1)))})
    fans = []
    for fid, rpm in re.findall(r"fan(\d+):\s+(\d+) RPM", out):
        rpm = int(rpm)
        if rpm > 0:
            fans.append({"label":"Chassis fan " + fid, "rpm": rpm})
    return {"temps": temps, "fans": fans}

def _band_counts(where):
    out = sh("runuser -u postgres -- psql -d document_intelligence -At -F'|' -c \"SELECT COALESCE(research_prior_band,'UNSCORED'), count(*) FROM document_processing_queue WHERE " + where + " GROUP BY 1 ORDER BY 1\"", 8)
    res = []
    for line in out.splitlines():
        if "|" in line:
            b, c = line.split("|")
            res.append({"band": b, "count": int(c)})
    return res

def queue():
    return {"waiting": _band_counts("status IN ('PENDING','PRE_RESEARCH_WAITING')"),
            "processing": _band_counts("status = 'PROCESSING'")}

def top():
    out=sh("ps -eo pcpu,pmem,comm --sort=-pcpu | head -8")
    res=[]
    for line in out.splitlines()[1:]:
        p=line.split(None,2)
        if len(p)==3 and p[2] not in ("ps","s13_web_dashboard.py"):
            res.append({"cpu":float(p[0]),"mem":float(p[1]),"cmd":p[2]})
    return res[:6]

def pipeline():
    out = sh("runuser -u postgres -- psql -d document_intelligence -At -F'|' -c \"SELECT status, COALESCE(research_prior_band,'UNSCORED'), count(*) FROM document_processing_queue GROUP BY 1,2\"", 10)
    stages = {}
    for line in out.splitlines():
        q = line.split("|")
        if len(q) == 3:
            try: n = int(q[2])
            except ValueError: continue
            stages.setdefault(q[0], {})[q[1]] = n
    def agg(keys):
        d = {}; total = 0
        for k in keys:
            for b, n in stages.get(k, {}).items():
                d[b] = d.get(b, 0) + n; total += n
        return {"total": total, "bands": d}
    lanes = {}
    lo = sh("runuser -u postgres -- psql -d document_intelligence -At -F'|' -c \"SELECT queue_lane, count(*) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING') GROUP BY 1\"", 8)
    for line in lo.splitlines():
        q = line.split("|")
        if len(q) == 2 and q[0]:
            try: lanes[q[0]] = int(q[1])
            except ValueError: pass
    return {"waiting": agg(["PENDING","PRE_RESEARCH_WAITING"]), "processing": agg(["PROCESSING"]),
            "completed": agg(["COMPLETED"]), "failed": agg(["FAILED"]), "no_links": agg(["NO_LINKS"]),
            "lanes": lanes}

def torgi_medals():
    out = sh("runuser -u postgres -- psql -d crm -At -F'|' -c \"SELECT COALESCE(o.current_effective_medal,'NULL'), count(*), count(DISTINCT o.procurement_id) FROM crm_procurement_category_opportunities o JOIN crm_procurements p ON p.id = o.procurement_id WHERE p.crm_stage='torgi' GROUP BY 1\"", 12)
    medals = {}; procs = 0
    for line in out.splitlines():
        q = line.split("|")
        if len(q) == 3:
            try:
                medals[q[0]] = int(q[1])
            except ValueError:
                pass
    tot = sh("runuser -u postgres -- psql -d crm -At -c \"SELECT count(DISTINCT o.procurement_id) FROM crm_procurement_category_opportunities o JOIN crm_procurements p ON p.id = o.procurement_id WHERE p.crm_stage='torgi' AND o.current_effective_medal IS NOT NULL\"", 12)
    try: procs = int(tot.strip())
    except ValueError: procs = 0
    return {"medals": medals, "procurements": procs}

_daily = {"data": {"new_s7": None, "queued": None, "completed": None, "medals": {}, "ts": None}}

def _compute_daily():
    try:
        new_s7 = sh("runuser -u postgres -- psql -d crm -At -c \"SELECT count(*) FROM crm_procurements WHERE crm_created_at >= current_date\"", 90)
        queued = sh("runuser -u postgres -- psql -d document_intelligence -At -c \"SELECT count(*) FROM document_processing_queue WHERE created_at >= current_date\"", 90)
        completed = sh("runuser -u postgres -- psql -d document_intelligence -At -c \"SELECT count(*) FROM document_processing_queue WHERE completed_at >= current_date\"", 90)
        med = sh("runuser -u postgres -- psql -d crm -At -F'|' -c \"SELECT COALESCE(current_effective_medal,'NULL'), count(*) FROM crm_procurement_category_opportunities WHERE updated_at >= current_date GROUP BY 1\"", 120)
        medals = {}
        for line in med.splitlines():
            q = line.split("|")
            if len(q) == 2:
                try: medals[q[0]] = int(q[1])
                except ValueError: pass
        def i(x):
            try: return int(x.strip())
            except Exception: return None
        _daily["data"] = {"new_s7": i(new_s7), "queued": i(queued), "completed": i(completed),
                          "medals": medals, "ts": time.strftime("%H:%M:%S")}
    except Exception:
        pass

def _daily_loop():
    while True:
        _compute_daily()
        time.sleep(120)

def snapshot():
    c=cpu_busy(); g=gpu()
    with _lock:
        _hist["cpu"].append(c); _hist["cpu"]=_hist["cpu"][-60:]
        if g: _hist["gpu"].append(g["util"]); _hist["gpu"]=_hist["gpu"][-60:]
        h={k:list(v) for k,v in _hist.items()}
    load=open("/proc/loadavg").read().split()[:3]
    up=sh("uptime -p").replace("up ","")
    return {"host":socket.gethostname(),"time":time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime":up,"load":load,"cpu":c,"temp":temp_c(),"mem":mem(),"gpu":g,
            "disks":disks(),"services":services(),"queue":queue(),"cooling":cooling(),"pipeline":pipeline(),"torgi":torgi_medals(),"daily":_daily["data"],"hist":h}

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>S13</title><style>
*{box-sizing:border-box} body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;font-size:22px}
header{padding:14px 22px;background:#161b22;border-bottom:2px solid #30363d;display:flex;justify-content:space-between;align-items:baseline}
h1{margin:0;font-size:30px;color:#58a6ff}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px 16px}
.card h2{margin:0 0 10px;font-size:20px;color:#8b949e;font-weight:600;text-transform:uppercase;letter-spacing:1px}
.bar{height:26px;background:#21262d;border-radius:6px;overflow:hidden}
.bar>span{display:block;height:100%;width:0;transition:width .4s}
.g{background:#2ea043}.y{background:#d29922}.r{background:#da3633}
.val{font-size:34px;font-weight:700}
.row{display:flex;justify-content:space-between;align-items:center;margin:6px 0}
.small{color:#8b949e;font-size:18px}
.svc{display:inline-flex;align-items:center;gap:8px;margin:5px 14px 5px 0;font-size:19px}
.dot{width:14px;height:14px;border-radius:50%}
.ok{background:#2ea043;box-shadow:0 0 8px #2ea043}.bad{background:#da3633;box-shadow:0 0 8px #da3633}
canvas{width:100%;height:120px}
.cool-row{display:flex;align-items:center;gap:36px;flex-wrap:wrap}
.fans{display:contents}
.temps{display:contents}
.fan{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;min-width:90px}
.blades{width:66px;height:66px;animation:spin linear infinite}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}

.temp{display:flex;align-items:center;gap:8px}.warn{background:#d29922;box-shadow:0 0 8px #d29922}
.disks{display:flex;gap:16px;justify-content:space-around;align-items:flex-start;flex-wrap:wrap}
.disk{display:flex;flex-direction:column;align-items:center;min-width:80px}
.donut{width:80px;height:80px}
.dname{font-size:18px;margin-top:4px}
.dsub{font-size:15px;color:#8b949e}
.dinfo{font-size:14px;color:#d29922;margin-top:2px;text-align:center;max-width:150px}
.warn{color:#d29922}
.cool-item{display:flex;align-items:center;gap:10px}
.ico{width:46px;height:46px}
.cval{font-size:30px;font-weight:700;line-height:1}


table{width:100%;border-collapse:collapse;font-size:19px}td{padding:3px 0;border-bottom:1px solid #21262d}
.qt{display:flex;align-items:center;gap:10px;margin:6px 0}.qt .nm{width:120px;color:#8b949e}
footer{padding:8px 22px;color:#484f58;font-size:16px}

.pipe{display:flex;align-items:stretch;gap:12px;flex-wrap:wrap}
.stage{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:10px 12px;min-width:150px;flex:1}
.stitle{font-size:15px;color:#8b949e;text-transform:uppercase;letter-spacing:1px}
.snum{font-size:34px;font-weight:700;margin:2px 0 6px}
.stage.w .snum{color:#58a6ff}.stage.p .snum{color:#d29922}.stage.c .snum{color:#2ea043}
.stage.f .snum{color:#da3633}.stage.n .snum{color:#c9a227}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid #30363d;border-radius:20px;padding:1px 9px;font-size:14px;color:#c9d1d9}
.arrow{display:flex;align-items:center;font-size:30px;color:#484f58}
.lanes{margin-top:8px;font-size:16px;color:#8b949e}

.mtiles{display:flex;gap:18px;flex-wrap:wrap}
.mtile{background:#0d1117;border:2px solid #30363d;border-radius:12px;padding:10px 22px;min-width:150px;text-align:center}
.mname{font-size:17px;letter-spacing:1px}
.mnum{font-size:38px;font-weight:700;line-height:1.1}
</style></head><body>
<header><h1 id="host">S13</h1><div class="small" id="clock"></div><div class="small" id="up"></div></header>
<div class="grid">
 <div class="card"><h2>CPU</h2><div class="val" id="cpu">-</div><div class="bar"><span id="cpub"></span></div><canvas id="cchart"></canvas><div class="small">load <span id="load"></span></div></div>
 <div class="card"><h2>RAM</h2><div class="val" id="ram">-</div><div class="bar"><span id="ramb"></span></div><div class="small" id="ramt"></div><div class="row small"><span>SWAP</span><span id="swap"></span></div><div class="bar"><span id="swapb"></span></div></div>
 <div class="card"><h2>GPU</h2><div class="val" id="gpu">-</div><div class="bar"><span id="gpub"></span></div><canvas id="gchart"></canvas><div class="small" id="gput"></div></div>
 <div class="card"><h2>Disks - health, temperature, free space</h2><div id="disks"></div></div>
  <div class="card" style="grid-column:span 2"><h2>Cooling - fans &amp; temperatures</h2><div id="cool"></div></div>
 
 <div class="card" style="grid-column:span 2"><h2>Today on S13 - new records / queue / categories</h2><div id="daily"></div></div>
 <div class="card" style="grid-column:span 2"><h2>Queue - waiting for parsing</h2><div id="q"></div></div>
 <div class="card" style="grid-column:span 2"><h2>In progress now</h2><div id="qp"></div></div>
 <div class="card" style="grid-column:span 4"><h2>Pipeline - document queue (conveyor)</h2><div id="pipe"></div></div>
 <div class="card" style="grid-column:span 4"><h2>Medals - procurements in bidding now (crm_stage=torgi)</h2><div id="torgi"></div></div>
</div><footer id="foot">?</footer>
<script>
const $=id=>document.getElementById(id);
function cls(p){return p>=85?'r':p>=70?'y':'g';}
function setbar(el,p){el.className=cls(p);el.style.width=Math.min(100,p)+'%';}
function line(cv,arr,color){const c=cv.getContext('2d');const w=cv.width=cv.clientWidth*2,h=cv.height=240;
 c.clearRect(0,0,w,h);c.strokeStyle='#30363d';c.lineWidth=2;for(let i=0;i<=4;i++){c.beginPath();c.moveTo(0,h*i/4);c.lineTo(w,h*i/4);c.stroke();}
 if(!arr||arr.length<2)return;c.strokeStyle=color;c.lineWidth=4;c.beginPath();
 arr.forEach((v,i)=>{const x=i*w/(arr.length-1),y=h-(v/100)*h;i?c.lineTo(x,y):c.moveTo(x,y);});c.stroke();
 const grad=c.createLinearGradient(0,0,0,h);grad.addColorStop(0,color+'55');grad.addColorStop(1,color+'00');c.fillStyle=grad;c.lineTo(w,h);c.lineTo(0,h);c.fill();}
async function tick(){try{const m=await (await fetch('/api/metrics')).json();
 $('host').textContent='S13: '+m.host;$('clock').textContent=m.time;$('up').textContent='up '+m.uptime;
 $('cpu').textContent=m.cpu+'%';setbar($('cpub'),m.cpu);$('load').textContent=m.load.join(' ');
 $('ram').textContent=m.mem.pct+'%';setbar($('ramb'),m.mem.pct);$('ramt').textContent=m.mem.used+'G / '+m.mem.total+'G (avail '+m.mem.avail+'G)';
 $('swap').textContent=m.mem.swap_used+'G / '+m.mem.swap_total+'G';setbar($('swapb'),m.mem.swap_pct);
 if(m.gpu){$('gpu').textContent=m.gpu.util+'%';setbar($('gpub'),m.gpu.util);$('gput').textContent='VRAM '+m.gpu.vram_used+'/'+m.gpu.vram_total+' MiB ('+m.gpu.vram_pct+'%), '+m.gpu.power+'/'+m.gpu.limit+' W, '+m.gpu.temp+' C';}
 else{$('gpu').textContent='n/a';}
 $('disks').innerHTML='<div class="disks">'+m.disks.map(d=>{const prob=d.health!='PASSED'||(d.pending||0)>0||(d.realloc||0)>0||(d.temp&&d.temp>=60);const pct=d.pct!=null?d.pct:0;const colp=pct>=85?'#da3633':pct>=70?'#d29922':'#2ea043';const info=[];if(d.temp!=null)info.push(d.temp+' C');if(d.pending)info.push('pending '+d.pending);if(d.realloc)info.push('realloc '+d.realloc);const ring=d.pct!=null?`<svg viewBox="0 0 42 42" class="donut"><circle cx="21" cy="21" r="15.9" fill="none" stroke="#21262d" stroke-width="6"/><circle cx="21" cy="21" r="15.9" fill="none" stroke="${colp}" stroke-width="6" stroke-dasharray="${pct} ${100-pct}" stroke-dashoffset="25" stroke-linecap="round"/><text x="21" y="24.5" text-anchor="middle" font-size="10.5" fill="#e6edf3">${pct}%</text></svg>`:`<svg viewBox="0 0 42 42" class="donut"><circle cx="21" cy="21" r="15.9" fill="none" stroke="#30363d" stroke-width="6"/><text x="21" y="24.5" text-anchor="middle" font-size="10" fill="#8b949e">n/a</text></svg>`;return `<div class="disk">${ring}<div class="dname">${prob?'<span class="warn">&#9888;</span> ':''}${d.dev}</div><div class="dsub">${d.mount?d.mount:'unmounted'}</div>${prob&&info.length?`<div class="dinfo">${info.join(' / ')}</div>`:''}</div>`;}).join('')+'</div>';

 const dl=m.daily||{};
 const md=dl.medals||{};
 const drow=(lbl,v,tone)=>`<div class="row"><span>${lbl}</span><b class="${tone||''}" style="font-size:28px">${v==null?'...':v}</b></div>`;
 const medchips=['GOLD','SILVER','BRONZE','WOOD','NULL'].filter(k=>md[k]).map(k=>`<span class="chip"><b style="color:${bc[k]||'#8b949e'}">${k==='NULL'?'no medal':k}</b> ${md[k]}</span>`).join('');
 $('daily').innerHTML=drow('New records today',dl.new_s7)+drow('Queued today',dl.queued)+drow('Completed today',dl.completed)+'<div class="chips">'+(medchips||'<span class="small">medals today: -</span>')+'</div><div class="lanes">updated '+(dl.ts||'-')+' (every 2 min)</div>';

const qbars=(arr)=>{const a=arr||[];const mx=Math.max(20,...a.map(x=>x.count));return a.length?a.map(x=>`<div class="qt"><span class="nm">${x.band}</span><span class="bar" style="flex:1"><span class="${cls(x.count/mx*100)}" style="width:${x.count/mx*100}%"></span></span><span>${x.count}</span></div>`).join(''):'<div class="small">nothing</div>';};
 $('q').innerHTML=qbars(m.queue.waiting);
 $('qp').innerHTML=qbars(m.queue.processing);

 const span=(v)=>Math.max(0.15,2.1-1.9*Math.min(1,Math.max(0,v)));
 const fanSvg=(dur,color)=>`<svg class="blades" style="animation-duration:${dur}s" viewBox="0 0 100 100"><g fill="${color}"><path d="M50 50 L49 6 A44 44 0 0 1 80 20 Z"/><path d="M50 50 L94 49 A44 44 0 0 1 80 80 Z" opacity=".85"/><path d="M50 50 L51 94 A44 44 0 0 1 20 80 Z"/><path d="M50 50 L6 51 A44 44 0 0 1 20 20 Z" opacity=".85"/></g><circle cx="50" cy="50" r="9" fill="#e6edf3"/></svg>`;
 let fansHtml=(m.cooling&&m.cooling.fans?m.cooling.fans:[]).map(f=>`<div class="fan">${fanSvg(span(f.rpm/3500).toFixed(2),'#58a6ff')}<div class="small">${f.label}<br><b style="font-size:24px">${f.rpm}</b> RPM</div></div>`).join('');
 if(m.gpu&&m.gpu.fan!=null){fansHtml+=`<div class="fan">${fanSvg(span(m.gpu.fan/100).toFixed(2),'#3fb950')}<div class="small">GPU fan<br><b style="font-size:24px">${m.gpu.fan}</b> %</div></div>`;}
 const tfind=(nm)=>{const a=(m.cooling&&m.cooling.temps)||[];const f=a.find(x=>String(x.label).toLowerCase().includes(nm));return f?f.c:null;};
const cpuT=tfind('package'); const mbT=tfind('motherboard'); const gpuT=(m.gpu?m.gpu.temp:null);
const tcol=v=>v>=80?'#da3633':v>=70?'#d29922':'#2ea043';
const iconCpu=`<svg viewBox="0 0 48 48" class="ico"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="12" y="12" width="24" height="24" rx="3"/><rect x="19" y="19" width="10" height="10"/><path d="M18 6v6M24 6v6M30 6v6M18 36v6M24 36v6M30 36v6M6 18h6M6 24h6M6 30h6M36 18h6M36 24h6M36 30h6"/></g></svg>`;
const iconGpu=`<svg viewBox="0 0 48 48" class="ico"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="5" y="14" width="38" height="20" rx="3"/><circle cx="17" cy="24" r="6"/><path d="M17 19v10M12 24h10M30 20h9M30 28h9"/></g></svg>`;
const iconMb=`<svg viewBox="0 0 48 48" class="ico"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="6" width="36" height="36" rx="3"/><rect x="14" y="14" width="14" height="14"/><path d="M32 14h6M32 19h6M32 24h6M12 32h24M12 37h16"/></g></svg>`;
const item=(icon,v)=>`<div class="cool-item" style="color:${tcol(v)}">${icon}<div class="cval">${v}<span style="font-size:17px"> C</span></div></div>`;
let tempsHtml='';
if(cpuT!=null)tempsHtml+=item(iconCpu,cpuT);
if(gpuT!=null)tempsHtml+=item(iconGpu,gpuT);
if(mbT!=null)tempsHtml+=item(iconMb,mbT);
$('cool').innerHTML=`<div class="cool-row">${fansHtml}${tempsHtml}</div>`;

 const bc={GOLD:'#d4a017',SILVER:'#a8b3bd',BRONZE:'#b06a2b',WOOD:'#6e4b2a',UNSCORED:'#8b949e'};
 const pstage=(title,d,tone)=>{if(!d)return '';const chips=Object.entries(d.bands||{}).sort().map(([b,n])=>`<span class="chip"><b style="color:${bc[b]||'#8b949e'}">${b}</b> ${n}</span>`).join('');return `<div class="stage ${tone}"><div class="stitle">${title}</div><div class="snum">${d.total}</div><div class="chips">${chips}</div></div>`;};
 const parr='<div class="arrow">&#10230;</div>';
 const pip=m.pipeline||{};
 const lanes=Object.entries(pip.lanes||{}).map(([k,v])=>`${k} ${v}`).join(' / ');
 
 const tg=m.torgi||{}; const mm=tg.medals||{};
 const mord=['GOLD','SILVER','BRONZE','WOOD','NULL'];
 $('torgi').innerHTML='<div class="mtiles">'+mord.filter(k=>mm[k]!=null).map(k=>`<div class="mtile" style="border-color:${bc[k]||'#30363d'}"><div class="mname" style="color:${bc[k]||'#8b949e'}">${k==='NULL'?'??? ??????':k}</div><div class="mnum">${mm[k]}</div></div>`).join('')+'</div><div class="lanes">distinct procurements with a medal: '+(tg.procurements||0)+'</div>';

 $('pipe').innerHTML='<div class="pipe">'+pstage('Waiting',pip.waiting,'w')+parr+pstage('Processing',pip.processing,'p')+parr+pstage('Completed',pip.completed,'c')+parr+pstage('Failed',pip.failed,'f')+parr+pstage('No links',pip.no_links,'n')+'</div><div class="lanes">waiting lanes: '+(lanes||'-')+'</div>';

 line($('cchart'),m.hist.cpu,'#58a6ff');line($('gchart'),m.hist.gpu,'#3fb950');
 $('foot').textContent='updated '+m.time+' ? refresh 2s';
}catch(e){$('foot').textContent='error: '+e;}}
tick();setInterval(tick,2000);window.addEventListener('resize',()=>tick());
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            ua=self.headers.get('User-Agent','') if hasattr(self,'headers') else ''
            sys.stderr.write('REQ %s %s UA=%s\n' % (getattr(self,'command',''), getattr(self,'path',''), ua))
        except Exception:
            pass
    def do_GET(self):
        if self.path.startswith("/api/metrics"):
            body=json.dumps(snapshot()).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            body=PAGE.encode()
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    cpu_busy()
    threading.Thread(target=_daily_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1",8899),H).serve_forever()
