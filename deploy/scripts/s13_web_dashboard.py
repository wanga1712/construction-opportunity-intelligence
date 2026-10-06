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

def queue():
    out=sh("runuser -u postgres -- psql -d document_intelligence -At -F'|' -c \"SELECT COALESCE(research_prior_band,'UNSCORED'), count(*) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING') GROUP BY 1 ORDER BY 1\"",8)
    res=[]
    for line in out.splitlines():
        if "|" in line:
            b,c=line.split("|"); res.append({"band":b,"count":int(c)})
    return res


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

def top():
    out=sh("ps -eo pcpu,pmem,comm --sort=-pcpu | head -8")
    res=[]
    for line in out.splitlines()[1:]:
        p=line.split(None,2)
        if len(p)==3 and p[2] not in ("ps","s13_web_dashboard.py"):
            res.append({"cpu":float(p[0]),"mem":float(p[1]),"cmd":p[2]})
    return res[:6]

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
            "disks":disks(),"services":services(),"queue":queue(),"cooling":cooling(),"top":top(),"hist":h}

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>S13</title><style>
*{box-sizing:border-box} body{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;font-size:22px}
header{padding:14px 22px;background:#161b22;border-bottom:2px solid #30363d;display:flex;justify-content:space-between;align-items:baseline}
h1{margin:0;font-size:30px;color:#58a6ff}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:16px}
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
.fans{display:flex;gap:30px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px}
.fan{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;min-width:90px}
.blades{width:66px;height:66px;animation:spin linear infinite}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.temps{display:flex;gap:24px;flex-wrap:wrap;font-size:21px}
.temp{display:flex;align-items:center;gap:8px}.warn{background:#d29922;box-shadow:0 0 8px #d29922}
table{width:100%;border-collapse:collapse;font-size:19px}td{padding:3px 0;border-bottom:1px solid #21262d}
.qt{display:flex;align-items:center;gap:10px;margin:6px 0}.qt .nm{width:120px;color:#8b949e}
footer{padding:8px 22px;color:#484f58;font-size:16px}
</style></head><body>
<header><h1 id="host">S13</h1><div class="small" id="clock"></div><div class="small" id="up"></div></header>
<div class="grid">
 <div class="card"><h2>CPU <span class="small" id="temp"></span></h2><div class="val" id="cpu">-</div><div class="bar"><span id="cpub"></span></div><canvas id="cchart"></canvas><div class="small">load <span id="load"></span></div></div>
 <div class="card"><h2>RAM</h2><div class="val" id="ram">-</div><div class="bar"><span id="ramb"></span></div><div class="small" id="ramt"></div><div class="row small"><span>SWAP</span><span id="swap"></span></div><div class="bar"><span id="swapb"></span></div></div>
 <div class="card"><h2>GPU</h2><div class="val" id="gpu">-</div><div class="bar"><span id="gpub"></span></div><canvas id="gchart"></canvas><div class="small" id="gput"></div></div>
 <div class="card" style="grid-column:span 3"><h2>Cooling - fans &amp; temperatures</h2><div id="cool"></div></div>
 <div class="card" style="grid-column:span 3"><h2>Disks - health, temperature, free space</h2><div id="disks"></div></div>
 <div class="card"><h2>Services</h2><div id="svcs"></div><div class="small" id="http"></div></div>
 <div class="card"><h2>Queue</h2><div id="q"></div></div>
 <div class="card" style="grid-column:span 3"><h2>Top CPU</h2><table id="top"></table></div>
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
 $('cpu').textContent=m.cpu+'%';setbar($('cpub'),m.cpu);$('temp').textContent=m.temp+' C';$('load').textContent=m.load.join(' ');
 $('ram').textContent=m.mem.pct+'%';setbar($('ramb'),m.mem.pct);$('ramt').textContent=m.mem.used+'G / '+m.mem.total+'G (avail '+m.mem.avail+'G)';
 $('swap').textContent=m.mem.swap_used+'G / '+m.mem.swap_total+'G';setbar($('swapb'),m.mem.swap_pct);
 if(m.gpu){$('gpu').textContent=m.gpu.util+'%';setbar($('gpub'),m.gpu.util);$('gput').textContent='VRAM '+m.gpu.vram_used+'/'+m.gpu.vram_total+' MiB ('+m.gpu.vram_pct+'%), '+m.gpu.power+'/'+m.gpu.limit+' W, '+m.gpu.temp+' C';}
 else{$('gpu').textContent='n/a';}
 $('disks').innerHTML=m.disks.map(d=>{const warn=(d.pending&&d.pending>0)||(d.realloc&&d.realloc>0)||d.health=='FAILED';const dot=d.health=='PASSED'?(warn?'warn':'ok'):'bad';return `<div class="row"><span><b>${d.dev}</b>  ${d.model||''}</span><span>${d.mount?d.mount:'(unmounted)'}</span></div>`+ (d.pct!=null?`<div class="bar"><span class="${cls(d.pct)}" style="width:${d.pct}%"></span></div>`: '')+ `<div class="small">`+ (d.pct!=null?`${d.used} used / ${d.size} (avail ${d.avail}) - ${d.pct}%  `:'')+ `<span class="dot ${dot}"></span> SMART ${d.health}`+ (d.temp!=null?`  -  ${d.temp} C`:'')+ (d.pending!=null&&d.pending>0?`  -  <b style="color:#da3633">pending ${d.pending}</b>`:'')+ (d.realloc!=null&&d.realloc>0?`  -  realloc ${d.realloc}`:'')+ `</div>`;}).join('');
 $('svcs').innerHTML=m.services.map(s=>`<span class="svc"><span class="dot ${s.state=='active'?'ok':'bad'}"></span>${s.label}</span>`).join('');
 const max=Math.max(80,...m.queue.map(q=>q.count));
 $('q').innerHTML=m.queue.map(q=>`<div class="qt"><span class="nm">${q.band}</span><span class="bar" style="flex:1"><span class="${cls(q.count/max*100)}" style="width:${q.count/max*100}%"></span></span><span>${q.count}</span></div>`).join('');

 const span=(v)=>Math.max(0.15,2.1-1.9*Math.min(1,Math.max(0,v)));
 const fanSvg=(dur,color)=>`<svg class="blades" style="animation-duration:${dur}s" viewBox="0 0 100 100"><g fill="${color}"><path d="M50 50 L49 6 A44 44 0 0 1 80 20 Z"/><path d="M50 50 L94 49 A44 44 0 0 1 80 80 Z" opacity=".85"/><path d="M50 50 L51 94 A44 44 0 0 1 20 80 Z"/><path d="M50 50 L6 51 A44 44 0 0 1 20 20 Z" opacity=".85"/></g><circle cx="50" cy="50" r="9" fill="#e6edf3"/></svg>`;
 let fansHtml=(m.cooling&&m.cooling.fans?m.cooling.fans:[]).map(f=>`<div class="fan">${fanSvg(span(f.rpm/3500).toFixed(2),'#58a6ff')}<div class="small">${f.label}<br><b style="font-size:24px">${f.rpm}</b> RPM</div></div>`).join('');
 if(m.gpu&&m.gpu.fan!=null){fansHtml+=`<div class="fan">${fanSvg(span(m.gpu.fan/100).toFixed(2),'#3fb950')}<div class="small">GPU fan<br><b style="font-size:24px">${m.gpu.fan}</b> %</div></div>`;}
 let tempsHtml=(m.cooling&&m.cooling.temps?m.cooling.temps:[]).map(t=>`<span class="temp"><span class="dot ${t.c>=80?'bad':t.c>=70?'warn':'ok'}"></span>${t.label}: <b>${t.c} C</b></span>`).join('');
 const gtmp=(m.gpu?`<span class="temp"><span class="dot ${m.gpu.temp>=80?'bad':m.gpu.temp>=70?'warn':'ok'}"></span>GPU: <b>${m.gpu.temp} C</b></span>`:'');
 $('cool').innerHTML=`<div class="fans">${fansHtml}</div><div class="temps">${tempsHtml}${gtmp}</div>`;

 $('top').innerHTML=m.top.map(t=>`<tr><td>${t.cmd}</td><td style="text-align:right">${t.cpu.toFixed(1)}%</td><td style="text-align:right">${t.mem.toFixed(1)}%</td></tr>`).join('');
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
    ThreadingHTTPServer(("127.0.0.1",8899),H).serve_forever()
