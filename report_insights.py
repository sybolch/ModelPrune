"""Offline EvalScope insights and accessible, interactive SVG radar charts."""
import html,json,math,statistics

def wilson(p,n):
    if not n or not 0<=p<=1:return None
    z=1.96;den=1+z*z/n;mid=(p+z*z/(2*n))/den
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return (max(0,mid-radius)*100,min(1,mid+radius)*100)

def percentile(values,q):
    if not values:return None
    values=sorted(values);index=(len(values)-1)*q;lo=int(index);hi=math.ceil(index)
    return values[lo]+(values[hi]-values[lo])*(index-lo)

def benchmark_rows(data):
    rows=[]
    for item in data.get('engine_reports',[]):
        report=item['data'];identity=report.get('primary_metric_identity')
        metric=next((m for m in report.get('metrics',[]) if identity and m.get('identity')==identity),None)
        if not metric:continue
        semantics=metric.get('semantics',{});value=metric.get('score');n=metric.get('num',0)
        if not isinstance(value,(int,float)) or not math.isfinite(value):continue
        ratio=semantics.get('direction')=='higher_is_better' and semantics.get('display_kind')=='percent' and 0<=value<=1
        execution=report.get('execution_summary',{})
        rows.append(dict(model=item['model'],suite=item['suite'],metric=identity['name'],value=value,n=n,
          score=value*(semantics.get('display_multiplier') or 1),unit=semantics.get('display_unit') or '',
          quality_ratio=ratio,ci=wilson(value,n) if ratio else None,
          complete=execution.get('incomplete') is False and execution.get('errored')==0 and execution.get('succeeded')==execution.get('requested'),
          requested=execution.get('requested'),succeeded=execution.get('succeeded'),errors=execution.get('errored'),
          version=report.get('evaluation_version')))
    return rows

def chart_data(data,rows):
    benchmarks=benchmark_rows(data)
    return [dict(name=row['model'],group=row['model_type'],rating=row.get('rating') or 0,
                 skills={cap:(stat['percent'] if stat['expected'] and stat['completed']==stat['expected'] else None) for cap,stat in row['skill_scores'].items()},
                 benchmarks={b['suite']:100*b['value'] for b in benchmarks if b['model']==row['model'] and b['quality_ratio'] and b['complete']})
            for row in sorted(rows,key=lambda r:-(r.get('rating') or 0))]

CSS='''
.insight-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:22px 0}.insight-cards article{margin:0}.insight-cards b{display:block;font-size:26px;color:#8ee8bf}.radar-controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.radar-controls label{display:grid;gap:6px;font-size:12px;color:#b9c7df}.radar-controls select{max-width:260px;padding:9px;background:#192333;color:#e1e8f5;border:1px solid #52637e;border-radius:6px}.radar-controls input{accent-color:#8ee8bf}.radar-models{display:flex;flex-wrap:wrap;gap:8px;border:0;padding:8px 0;margin:0}.radar-models label{display:inline-flex;gap:7px;align-items:center;border:1px solid;border-radius:6px;padding:8px;font-size:13px;cursor:pointer}.radar-actions{display:flex;gap:8px;margin:12px 0}.radar-actions button{background:#192333;color:#e1e8f5;border:1px solid #52637e;border-radius:5px;padding:8px 14px;cursor:pointer}.radar-grid{display:grid;grid-template-columns:minmax(300px,1fr) minmax(250px,1fr);align-items:center;gap:24px}.radar-grid svg{display:block;width:100%;max-width:650px;margin:auto}.radar-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:14px}.radar-legend span{border-left:5px solid;padding-left:8px}.radar-values th,.radar-values td{white-space:normal;padding:10px}.report-tools{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.report-tools input,.report-tools select{padding:9px;background:#192333;color:#e1e8f5;border:1px solid #52637e;border-radius:5px}@media(max-width:850px){.radar-grid{grid-template-columns:1fr}.radar-controls select{max-width:100%}}
'''

SCRIPT=r'''
(()=>{
function revealSection(){const key=decodeURIComponent(location.hash.slice(1));const section=document.getElementById(key);if(section?.tagName==='DETAILS')section.open=true;}
window.addEventListener('hashchange',revealSection);revealSection();
const models=JSON.parse(document.getElementById('radar-data').textContent);
const visibility=new Map(models.map(m=>[m.name,true]));
const color=m=>'hsl('+((models.indexOf(m)*137.508+145)%360).toFixed(1)+' 70% 70%)';
const el=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
function node(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
function label(key){return ({modelprune_core:'Local core',modelprune_coding:'Coding',modelprune_vision:'Vision',modelprune_audio:'Listening',modelprune_speech:'Speech output',modelprune_tools:'Tools',modelprune_thinking:'Thinking',completion:'Completion',decision:'Decision',coding:'Coding',vision:'Vision',audio:'Listening',speech:'Speech output',tools:'Tools',thinking:'Thinking',boolq:'BoolQ',gsm8k:'GSM8K',ifeval:'IFEval (strict)'})[key]||key;}
function available(){return models.filter(m=>m.group===el('radar-group').value);}
function reset(){const list=el('radar-models');list.replaceChildren();available().forEach(m=>{const label=document.createElement('label'),toggle=document.createElement('input'),name=document.createElement('span');toggle.type='checkbox';toggle.checked=visibility.get(m.name);toggle.setAttribute('aria-label','Show '+m.name);name.textContent=m.name;label.style.borderColor=color(m);toggle.addEventListener('change',()=>{visibility.set(m.name,toggle.checked);draw();});label.append(toggle,name);list.append(label);});draw();}

function draw(){
 const selected=available().filter(m=>visibility.get(m.name));
 const mode=el('radar-mode').value,common=el('radar-common').checked;
 let axes=[...new Set(selected.flatMap(m=>Object.keys(m[mode])))].sort();if(common)axes=axes.filter(k=>selected.every(m=>m[mode][k]!=null));
 const svg=el('radar-svg');svg.replaceChildren();svg.append(node('title',{},'Model quality comparison'));svg.append(node('desc',{},'Percent quality on a fixed zero to one hundred scale. Unmeasured skills are not zero.'));
 const values=el('radar-values');values.replaceChildren();const head=document.createElement('thead'),hr=document.createElement('tr');
 ['Axis',...selected.map(m=>m.name)].forEach(text=>{const th=document.createElement('th');th.textContent=text;hr.append(th);});head.append(hr);values.append(head);const body=document.createElement('tbody');
 for(const key of axes){const tr=document.createElement('tr');const title=document.createElement('th');title.textContent=label(key);tr.append(title);for(const m of selected){const td=document.createElement('td');td.textContent=m[mode][key]==null?'Not tested':m[mode][key].toFixed(1)+'%';tr.append(td);}body.append(tr);}values.append(body);
 el('radar-legend').replaceChildren();selected.forEach((m,i)=>{const span=document.createElement('span');span.style.borderColor=color(m);span.textContent=m.name;el('radar-legend').append(span);});
 if(!selected.length){el('radar-note').textContent='No models selected. Enable a model toggle or choose Show all.';return;}
 if(axes.length<3){el('radar-note').textContent='A radar needs at least three measured axes. Choose benchmark axes, other models, or disable “shared axes only”. Available values are shown in the table.';return;}
 el('radar-note').textContent='Larger means higher measured quality. '+(common?'Only axes measured for every selected model are shown.':'Missing measurements are gaps; incomplete profiles are not filled.')+' Use the table for exact values; polygon area is not an overall rating.';
 const cx=330,cy=280,R=185,point=(i,v)=>[cx+R*v/100*Math.cos(-Math.PI/2+i*2*Math.PI/axes.length),cy+R*v/100*Math.sin(-Math.PI/2+i*2*Math.PI/axes.length)];
 for(const value of [20,40,60,80,100]){svg.append(node('polygon',{points:axes.map((_,i)=>point(i,value).join(',')).join(' '),fill:'none',stroke:'#34445d'}));svg.append(node('text',{x:cx+5,y:cy-R*value/100-4,fill:'#a5b5cf','font-size':11},value+'%'));}
 axes.forEach((key,i)=>{const [x,y]=point(i,100),[lx,ly]=point(i,119);svg.append(node('line',{x1:cx,y1:cy,x2:x,y2:y,stroke:'#34445d'}));svg.append(node('text',{x:lx,y:ly,fill:'#dce6f5','text-anchor':lx<cx-20?'end':lx>cx+20?'start':'middle','dominant-baseline':'middle','font-size':13},label(key)));});
 selected.forEach((m,j)=>{const vals=axes.map(k=>m[mode][k]),complete=vals.every(v=>v!=null);if(complete)svg.append(node('polygon',{points:vals.map((v,i)=>point(i,v).join(',')).join(' '),fill:color(m),'fill-opacity':.08,stroke:color(m),'stroke-width':2.5}));else vals.forEach((v,i)=>{const next=(i+1)%vals.length;if(v!=null&&vals[next]!=null){const a=point(i,v),b=point(next,vals[next]);svg.append(node('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:color(m),'stroke-width':2.5}));}});vals.forEach((v,i)=>{if(v==null)return;const [x,y]=point(i,v),dot=node('circle',{cx:x,cy:y,r:4,fill:color(m)});dot.append(node('title',{},m.name+' · '+label(axes[i])+': '+v.toFixed(1)+'%'));svg.append(dot);});});
}
el('radar-group').addEventListener('change',()=>{if(el('radar-group').value==='Decision')el('radar-mode').value='benchmarks';reset();});
for(const control of [el('radar-mode'),el('radar-common')])control.addEventListener('change',draw);
el('radar-show-all').addEventListener('click',()=>{available().forEach(m=>visibility.set(m.name,true));reset();});
el('radar-hide-all').addEventListener('click',()=>{available().forEach(m=>visibility.set(m.name,false));reset();});reset();
const filter=()=>{const query=el('evidence-search').value.toLowerCase(),state=el('evidence-state').value;let count=0;document.querySelectorAll('#task-evidence > details').forEach(n=>{const matches=n.dataset.search.includes(query)&&(state==='all'||n.dataset.outcome===state);n.hidden=!matches;if(matches)count++;});el('evidence-count').textContent=count+' matching attempts';};
if(el('evidence-search')){el('evidence-search').addEventListener('input',filter);el('evidence-state').addEventListener('change',filter);filter();}
})();
'''

def render(data,rows):
    esc=lambda v:html.escape(str(v if v is not None else '—'))
    benchmarks=benchmark_rows(data);all_results=data['results']+data.get('image_benchmark',{}).get('results',[])
    errors=sum(bool(r.get('error')) for r in all_results)
    complete=sum(b['complete'] for b in benchmarks)
    page='<div class="insight-cards">'+''.join('<article><b>'+esc(v)+'</b><small>'+esc(label)+'</small></article>' for v,label in [(len(rows),'Benchmarked language/decision models'),(len(all_results),'Scored attempts'),(f'{complete}/{len(benchmarks)}','EvalScope suites completed'),(errors,'Runtime / output-limit errors')])+'</div>'
    if data.get('standard_limit'):
        page+='<p class="meta">Standard datasets are limited to '+esc(data['standard_limit'])+' samples per subset. Confidence intervals below show how uncertain small accuracy samples are; local fixtures are fixed diagnostic tasks, not representative random samples.</p>'
    groups=sorted({row['model_type'] for row in rows},reverse=True)
    payload=json.dumps(chart_data(data,rows),ensure_ascii=False).replace('<',chr(92)+'u003c').replace('>',chr(92)+'u003e').replace('&',chr(92)+'u0026')
    page+='<section id="radar"><h2>Model radar comparison</h2><div class="radar-controls"><label>Model group<select id="radar-group">'+''.join('<option>'+esc(g)+'</option>' for g in groups)+'</select></label><label>Axes<select id="radar-mode"><option value="skills">Measured skills</option><option value="benchmarks">EvalScope benchmarks</option></select></label>'
    page+='<label><span>Comparison scope</span><span><input id="radar-common" type="checkbox" checked> Shared axes only</span></label></div><div class="radar-actions"><button id="radar-show-all" type="button">Show all</button><button id="radar-hide-all" type="button">Hide all</button></div><fieldset id="radar-models" class="radar-models" aria-label="Visible models"></fieldset><div class="radar-grid"><svg id="radar-svg" viewBox="0 0 660 560" role="img" aria-label="Model radar comparison"></svg><div><p id="radar-note" aria-live="polite"></p><div class="scroll"><table class="radar-values" id="radar-values"></table></div></div></div><div id="radar-legend" class="radar-legend"></div><noscript><p>Enable JavaScript for interactive radars. All scores remain available in the comparison and benchmark tables.</p></noscript><script type="application/json" id="radar-data">'+payload+'</script></section>'
    page+='<details id="benchmarks"><summary>EvalScope benchmark breakdown ('+str(len(benchmarks))+' suite results)</summary><p>Primary metrics retain EvalScope names and units. The 95% Wilson intervals apply to standard binary accuracy samples only; they are indicative because these are bounded, fixed samples.</p><div class="scroll"><table><thead><tr><th>Model</th><th>Benchmark</th><th>Primary metric</th><th>Samples</th><th>Score</th><th>95% interval</th><th>Execution</th></tr></thead><tbody>'
    for b in sorted(benchmarks,key=lambda b:(b['model'],b['suite'])):
        ci=b['ci'] if not b['suite'].startswith('modelprune_') else None
        interval=f'{ci[0]:.1f}–{ci[1]:.1f}%' if ci else '—'
        status='Complete' if b['complete'] else 'Incomplete / errors'
        page+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [b['model'],b['suite'],b['metric'],b['n'],f"{b['score']:.2f}{b['unit']}",interval,status])+'</tr>'
    page+='</tbody></table></div></details><details id="performance"><summary>Latency and errors by model</summary><p>P50 and P95 use recorded inference/request times without runtime errors, including model loading. Standard calls include proxy checks. These are latency percentiles, not tokens/second; no unavailable TTFT is inferred.</p><div class="scroll"><table><thead><tr><th>Model</th><th>Attempts</th><th>P50</th><th>P95</th><th>Errors</th></tr></thead><tbody>'
    for name in sorted({r['model'] for r in all_results}):
        attempts=[r for r in all_results if r['model']==name];times=[r['seconds'] for r in attempts if not r.get('error')]
        fmt=lambda value:'—' if value is None else f'{value:.3f} s'
        page+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [name,len(attempts),fmt(percentile(times,.5)),fmt(percentile(times,.95)),sum(bool(r.get('error')) for r in attempts)])+'</tr>'
    page+='</tbody></table></div></details>'
    calibration=[]
    for item in data.get('engine_reports',[]):
        for metric in item['data'].get('metrics',[]):
            identity=metric.get('identity',{});value=metric.get('score')
            if identity.get('name') in ('nll','brier','ece','aurc') and isinstance(value,(int,float)) and math.isfinite(value):
                dimensions=', '.join(str(v) for v in identity.get('dimensions',{}).values())
                calibration.append((item['model'],item['suite'],identity['name']+(' · '+dimensions if dimensions else ''),metric.get('num'),f'{value:.4f}'))
    if calibration:
        page+='<details id="calibration"><summary>Decision confidence calibration</summary><p>EvalScope probability-based metrics: lower is better for NLL, Brier, ECE and AURC. These are separate from accuracy and are never plotted as higher-is-better radar scores. Small samples limit conclusions.</p><div class="scroll"><table><thead><tr><th>Model</th><th>Benchmark</th><th>Metric ↓</th><th>Samples</th><th>Value</th></tr></thead><tbody>'
        for row in calibration:page+='<tr>'+''.join('<td>'+esc(value)+'</td>' for value in row)+'</tr>'
        page+='</tbody></table></div></details>'
    return page
