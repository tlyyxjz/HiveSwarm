"""蜂巢实时面板——Python标准库，不需要安装任何东西"""
import json, time, threading, http.server, os
from pathlib import Path

HOME = Path.home()
HIVE = HOME / ".claude/data/hive-mind.json"
DISPATCH = HOME / ".claude/data/hive-dispatch.json"
STATE = HOME / ".claude/data/overseer-state.json"

def build_data():
    try: hive = json.loads(HIVE.read_text(encoding="utf-8"))
    except: hive = {}
    try: dispatch = json.loads(DISPATCH.read_text(encoding="utf-8"))
    except: dispatch = {}
    try: state = json.loads(STATE.read_text(encoding="utf-8"))
    except: state = {}
    
    agents = []
    for a, s in hive.get("agent_states", {}).items():
        agents.append({"name": a, "status": s.get("status","?"), "findings": s.get("findings",0)})
    
    return {
        "mission": hive.get("mission","?")[:80],
        "mode": dispatch.get("mode", "idle"),
        "topology": dispatch.get("topology", "?"),
        "label": dispatch.get("label", ""),
        "agents": agents,
        "queue": hive.get("agent_queue", []),
        "done": hive.get("completed_agents", []),
        "findings_count": len(hive.get("findings", [])),
        "last_findings": hive.get("findings", [])[-5:],
        "bash_streak": state.get("bash_streak", 0),
        "pi_total_violations": state.get("pi_violations", 0),
    }

HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>HiveSwarm 实时战况</title>
<meta http-equiv="refresh" content="2">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#c0c0d0;font-family:Consolas,monospace;padding:16px}
h1{color:#06b6d4;font-size:1.2em;margin-bottom:8px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.card{background:#12121a;border:1px solid #1e1e2e;border-radius:6px;padding:12px}
.card h2{font-size:.7em;color:#64748b;margin-bottom:6px;text-transform:uppercase;letter-spacing:.1em}
.agent{display:flex;align-items:center;gap:6px;padding:3px 0;font-size:.8em}
.dot{width:7px;height:7px;border-radius:50%}
.green{background:#22c55e;box-shadow:0 0 5px #22c55e}
.yellow{background:#eab308;box-shadow:0 0 5px #eab308}
.white{background:#64748b}
.flag{background:#1a1212;border-left:3px solid #ef4444;padding:4px 8px;margin:3px 0;font-size:.75em;border-radius:3px}
.flag.crit{border-color:#dc2626}.flag.high{border-color:#f97316}.flag.med{border-color:#eab308}
.metric{font-size:1.4em;font-weight:bold}.red{color:#ef4444}.green{color:#22c55e}.yellow{color:#eab308}
.bar{height:3px;background:#1e1e2e;border-radius:2px;margin:4px 0;overflow:hidden}
.bar-fill{height:100%;border-radius:2px}
.pi-ok{background:#0a1a0a;color:#22c55e;font-size:.8em;padding:6px;border-radius:4px;margin-top:4px}
.pi-warn{background:#1a1a0a;color:#eab308;font-size:.8em;padding:6px;border-radius:4px;margin-top:4px}
.pi-block{background:#1a0a0a;color:#ef4444;font-size:.8em;padding:6px;border-radius:4px;margin-top:4px}
</style></head><body>
<h1>HiveSwarm 实时战况 <span style="font-size:.6em;color:#64748b">(auto-refresh 2s)</span></h1>
<div class="grid">
<div class="card"><h2>Agent</h2><div id="agents"></div></div>
<div class="card"><h2>发现</h2><div id="findings"></div></div>
<div class="card"><h2>指标</h2><div id="metrics"></div></div>
<div class="card"><h2>PI</h2><div id="pi"></div></div>
</div>
<script>
var D = DATA_PLACEHOLDER;
(function(){
var a=D.agents||[],q=D.queue||[],d=D.done||[];
document.getElementById("agents").innerHTML=a.length?a.map(function(x){
var c=x.status==="hunting"?"green":x.status==="done"?"white":"yellow";
return'<div class=agent><span class="dot '+c+'"></span><b>'+x.name+"</b> "+x.status+" | "+(x.findings||0)+"</div>"
}).join("")+(q.length?"<p style=color:#64748b;margin-top:4px>队列: "+q.join(",")+"</p>":"")+(d.length?"<p style=color:#22c55e>已完成: "+d.join(",")+"</p>":""):"<p style=color:#64748b>无活跃</p>";
var f=D.last_findings||[];
document.getElementById("findings").innerHTML=f.length?f.map(function(x){
var s=x.severity||"info",c=s==="critical"?"crit":s==="high"?"high":s==="medium"?"med":"";
return'<div class="flag '+c+'"><b>['+s.toUpperCase()+"]</b> "+(x.type||"?")+"<br><span style=color:#64748b>"+(x.agent||"?")+" @ "+(x.endpoint||"?")+"</span></div>"
}).join(""):"<p style=color:#64748b>暂无</p>";
var n=D.findings_count||0,bp=D.bash_streak||0;
document.getElementById("metrics").innerHTML='<div class=metric style=color:'+(n>=3?"#22c55e":n>=1?"#eab308":"#ef4444")+'>'+n+'</div>发现 | Bash: '+bp+'/3<div class=bar><div class="bar-fill" style="width:'+(bp*33)+'%;background:'+(bp>=3?"#ef4444":bp>=2?"#eab308":"#22c55e")+'"></div></div>'+'<div style=margin-top:6px;font-size:.75em>模式: '+(D.mode||"?")+' | 拓扑: '+(D.topology||"?")+'</div>';
var s=D.bash_streak||0,p=s>=3?"pi-block":s>=2?"pi-warn":"pi-ok",m=s>=3?"阻断:强派PI":s>=2?"警告:建议派PI":"正常";
document.getElementById("pi").innerHTML='<div class="'+p+'">'+m+' | 违规: '+(D.pi_total_violations||0)+'</div>';
})();
</script>
</body></html>"""

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        data = build_data()
        html = HTML.replace("DATA_PLACEHOLDER", json.dumps(data, ensure_ascii=False))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    def log_message(self, *a): pass

if __name__ == "__main__":
    os.chdir(str(HOME / "HiveSwarm"))
    print("HiveSwarm 实时面板: http://localhost:8765")
    print("不需要刷新——每2秒自动更新")
    http.server.HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
