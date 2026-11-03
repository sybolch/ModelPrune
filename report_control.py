"""Local report run control; no third-party scripts or arbitrary command input."""
import html,json
from pathlib import Path

CONFIG=Path(__file__).resolve().parent/'.report-server.json'
CSS='''
.run-control{margin:18px 0;padding:14px;background:#192333;border:1px solid #334057;border-radius:9px}.run-control button{background:#8ee8bf;color:#101621;border:0;border-radius:6px;padding:11px 18px;font:600 14px system-ui;cursor:pointer}.run-control button:disabled{opacity:.6;cursor:wait}.run-control progress{display:block;width:100%;height:22px;accent-color:#8ee8bf}.run-control [hidden]{display:none!important}.run-control p{margin:8px 0 0;font-size:13px}.run-control code{overflow-wrap:anywhere}
'''
SCRIPT=r'''
(()=>{
const config=JSON.parse(document.getElementById('run-config').textContent),button=document.getElementById('run-benchmark'),discovery=document.getElementById('run-discovery'),partial=document.getElementById('run-partial'),panel=document.getElementById('benchmark-progress'),bar=document.getElementById('benchmark-progress-bar'),label=document.getElementById('benchmark-progress-label'),message=document.getElementById('benchmark-run-message');
let runningId=null,requestPending=false,failures=0;
function running(yes){button.hidden=yes;discovery.hidden=yes;partial.hidden=yes;panel.hidden=!yes;}
async function api(path,method='GET'){const response=await fetch(config.url+path,{method,headers:{Authorization:'Bearer '+config.token,...(method==='POST'?{'Content-Type':'application/json'}:{})},...(method==='POST'?{body:'{}'}:{}),cache:'no-store',signal:AbortSignal.timeout(10000)});const result=await response.json();if(!response.ok)throw Error(result.error||'Local service returned '+response.status);return result;}
function update(state){
 const active=state.state==='running';running(active);button.disabled=false;discovery.disabled=false;partial.disabled=false;
 if(active){runningId=state.id;bar.max=state.total_samples||1;if(state.total_samples){bar.value=Math.min(state.completed_samples,state.total_samples);}else{bar.removeAttribute('value');}
 label.textContent=state.kind==='discovery'?'Discovering installed models…':state.total_samples?state.completed_samples+' / '+state.total_samples+' samples · '+state.completed_jobs+' / '+state.total_jobs+' suites':'Discovering installed models…';
 message.textContent=state.current?state.current:'Preparing benchmark…';
 }else{message.textContent=state.state==='failed'?(state.kind==='discovery'?'Discovery failed: ':'Benchmark failed: ')+state.error:state.state==='completed'?(state.message||(state.kind==='discovery'?'Discovery complete. Inventory updated.':'Benchmark complete. Results updated.')):'Ready to benchmark installed models, including remote registrations.';
 if(state.state==='completed'&&runningId===state.id){runningId=null;location.reload();}}
}
async function poll(){if(requestPending)return;try{update(await api('/api/status'));failures=0;}catch(error){failures++;if(!runningId){running(false);button.disabled=false;message.textContent='Local benchmark service is unavailable. Start it with: '+config.start_command;}else{message.textContent='Reconnecting to the benchmark service…';}}}
async function start(path){if(requestPending)return;requestPending=true;button.disabled=true;discovery.disabled=true;partial.disabled=true;try{const state=await api(path,'POST');runningId=state.id;update(state);}catch(error){button.disabled=false;discovery.disabled=false;partial.disabled=false;message.textContent=error.message;await poll();}finally{requestPending=false;}}
button.addEventListener('click',()=>start('/api/run'));discovery.addEventListener('click',()=>start('/api/discover'));partial.addEventListener('click',()=>start('/api/partial'));
poll();setInterval(poll,2000);
})();
'''

def render(data):
    settings=data.get('run_control')
    if not settings and CONFIG.exists():
        try:
            config=json.loads(CONFIG.read_text())
            settings={'url':'http://127.0.0.1:'+str(config['port']),'token':config['token'],'start_command':config.get('start_command') or 'systemctl --user start '+config.get('service_name','modelprune-report')+'.service'}
        except (OSError,ValueError,KeyError):pass
    settings=settings or {'url':'http://127.0.0.1:8791','token':'','start_command':'python3 report_server.py --config .report-server.json'}
    payload=json.dumps(settings).replace('<',chr(92)+'u003c')
    return '<div class="run-control"><button id="run-benchmark" type="button">Run benchmark</button> <button id="run-discovery" type="button">Rerun discovery</button> <button id="run-partial" type="button">Benchmark new models</button><div id="benchmark-progress" hidden><progress id="benchmark-progress-bar" aria-label="Benchmark progress"></progress><p id="benchmark-progress-label" role="status" aria-live="polite">Preparing benchmark…</p></div><p id="benchmark-run-message" aria-live="polite">Connecting to local benchmark service…</p></div><script id="run-config" type="application/json">'+payload+'</script>'
