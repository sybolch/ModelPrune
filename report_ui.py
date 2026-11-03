"""Compact offline benchmark report. All model-provided content is escaped."""
import html
import base64
import hashlib
import json
import math
import re
import domain_sections
import report_insights
import report_control
from skill_tasks import ICONS, ROOT


def compact_number(value):
    if value is None:return '—'
    original=str(value)
    match=re.fullmatch(r'\s*([0-9]+(?:\.[0-9]+)?)\s*([KMBT]?)\s*',original.replace(',',''),re.I)
    if not match:return '—' if original in ('?','') else original
    number=float(match[1])*{'':1,'K':1e3,'M':1e6,'B':1e9,'T':1e12}[match[2].upper()]
    if not math.isfinite(number):return '—'
    for scale,suffix in [(1e12,'T'),(1e9,'B'),(1e6,'M'),(1e3,'K')]:
        if number>=scale:
            rounded=round(number/scale,1)
            if rounded>=1000 and suffix!='T':return compact_number(scale*1000)
            return f'{rounded:.1f}'.rstrip('0').rstrip('.')+suffix
    return f'{number:.1f}'.rstrip('0').rstrip('.')


def render(data,rows,decisions):
    esc=lambda x:html.escape(str(x if x is not None else '—'))
    decision_map={decision['model']:decision for decision in decisions}
    percent=lambda x:'—' if x is None else f'{x:.1f}%'
    def comparison_table(group_rows,group_id):
        table='<table id="comparison-'+group_id+'"><thead><tr>'+''.join('<th>'+name+'</th>' for name in ['Model','Parameters','Context','Skills','Task success','Speed','Overall'])+'</tr></thead><tbody>'
        for row in sorted(group_rows,key=lambda r:-(r['rating'] or 0)):
            icons=''
            for cap in sorted(row['capabilities']):
                stat=row['skill_scores'][cap]
                state='untested' if not stat['expected'] or stat['completed']<stat['expected'] else 'failed' if not stat['passed'] else 'mixed' if stat['passed']<stat['expected'] else 'passed'
                tip=f"{cap}: {stat['passed']}/{stat['expected']} passed; {stat['completed']} attempted; {stat['errors']} errors ({state})"
                if stat.get('median_seconds') is not None: tip+=f"; median {stat['median_seconds']:.3f}s"
                icons+=f'<span class="skill {state}" title="{esc(tip)}" aria-label="{esc(tip)}">{esc(ICONS.get(cap,"?"))}</span>'
            architecture=esc(row.get('architecture_type','Unknown'))
            if row.get('expert_count'): architecture+=f" · {row.get('experts_used')}/{row['expert_count']} experts"
            context=compact_number(row['context']) if row['context'] else '—'
            speed=f"{row['median_seconds']:.3f} s" if row['median_seconds'] is not None else '—'
            rating=f"{row['rating']:.1f}<small>/100</small>" if row['rating'] is not None else '—'
            status='All skills tested' if row['skill_coverage']==1 and row['completed']==row['expected'] else 'Incomplete coverage'
            decision=decision_map.get(row['model'])
            tag=''
            if decision and decision.get('replacement'):
                replacement=decision.get('replacement')
                tradeoff='tradeoff' in decision['status'].lower()
                label=('Remote tradeoff' if 'remote execution' in decision['status'].lower() else 'Context tradeoff' if tradeoff else 'Replaceable')+' → '+replacement if replacement else 'Keep'
                state='tradeoff' if tradeoff else 'replaceable' if replacement else 'keep'
                tag='<details class="overlap-tag '+state+'" title="'+esc(decision['status'])+'"><summary>'+esc(label)+'</summary><p>'+esc(decision['reason'])+'</p></details>'
            aliases=''
            if row.get('aliases'):
                aliases='<details class="overlap-tag"><summary>Aliases ('+str(len(row['aliases']))+')</summary><p>'+''.join(esc(alias['name'])+(' · context '+esc(compact_number(alias['context_override'])) if alias.get('context_override') else '')+'<br>' for alias in row['aliases'])+'Same model weights; runtime defaults can differ.</p></details>'
            if row.get('benchmark_registration'):aliases+='<small>Benchmarked via '+esc(row['benchmark_registration'])+'</small>'
            table+='<tr><td><strong>'+esc(row['model'])+'</strong>'+('<small class="execution-remote">☁ Remote via Ollama</small>' if row.get('remote') else '')+tag+aliases+'<small>'+esc(f"{row['size_gb']} GB · {row['quantization']}")+'</small></td><td>'+esc(compact_number(row['parameters']))+(' total' if row.get('architecture_type')=='MoE' else '')+'<small>'+architecture+'</small></td><td title="'+esc(f"{row['context']:,}" if row['context'] else 'Unknown')+'">'+esc(context)+'</td><td class="icons">'+icons+'</td><td>'+percent(row['success_rate'])+'<small>'+esc(f"{sum(s['passed'] for s in row['skill_scores'].values())}/{row['expected']} tasks passed")+'</small></td><td title="Median end-to-end latency; lower is faster">'+speed+'</td><td class="rating">'+rating+'<small>'+esc(status)+'</small></td></tr>'
        table+='</tbody></table>'
        return table
    tables=''
    for model_type,title,group_id in [("Generative","Generative models","generative"),("Decision","Decision models","decision")]:
        group_rows=[row for row in rows if row["model_type"]==model_type]
        if group_rows:
            tables+='<h2 id="models-'+group_id+'">'+title+'</h2><div class="scroll">'+comparison_table(group_rows,group_id)+'</div>'
    domain_tables=''
    for name,title in domain_sections.DOMAINS.items():
        domain_tables+='<section id="'+name+'"><h2>'+title+'</h2>'
        if name=='image-generation':
            image_data=data.get('image_benchmark',{})
            domain_tables+='<p>'+esc(image_data.get('method','Image generation has not been benchmarked. An installed image checkpoint requires the optional ComfyUI adapter; components such as a VAE are not standalone generators.'))+'</p>'
            image_results=image_data.get('results',[])
            if image_results:
                import statistics
                domain_tables+='<div class="scroll"><table><thead><tr><th>Model</th><th>Task success</th><th>Speed</th><th>Quality</th></tr></thead><tbody>'
                for model_name in sorted({r['model'] for r in image_results}):
                    attempts=[r for r in image_results if r['model']==model_name]
                    passed=sum(r['points']>0 for r in attempts)
                    expected=len(image_data.get('tasks',[]))
                    possible=sum(t['level'] for t in image_data.get('tasks',[]))
                    quality=100*sum(r['points'] for r in attempts)/possible if possible else None
                    domain_tables+='<tr><td>'+esc(model_name)+'</td><td>'+percent(100*passed/expected if expected else None)+'<small>'+esc(f"{passed}/{expected} passed")+'</small></td><td>'+esc(f"{statistics.median(r['seconds'] for r in attempts):.2f} s")+'</td><td>'+percent(quality)+'</td></tr>'
                domain_tables+='</tbody></table></div><h3>Generated outputs</h3>'
                domain_tables+='<div class="scroll"><table><thead><tr><th>Model</th><th>Task</th><th>Result</th><th>Speed</th><th>Output</th></tr></thead><tbody>'
                for result in image_results:
                    preview='<img width="160" alt="Generated benchmark image" src="data:image/png;base64,'+esc(result['image_b64'])+'">' if result.get('image_b64') else esc(result.get('error','No image'))
                    domain_tables+='<tr><td>'+esc(result['model'])+'</td><td>'+esc(result['task'])+'</td><td>'+esc(str(result['points'])+'/'+str(result['level']))+'</td><td>'+esc(f"{result['seconds']:.2f} s")+'</td><td>'+preview+'</td></tr>'
                domain_tables+='</tbody></table></div><details><summary>Image generation evidence</summary><pre>'+esc(json.dumps({**image_data,'results':[{k:v for k,v in r.items() if k!='image_b64'} for r in image_results]},indent=2))+'</pre></details>'
            image_models=[model for model in data.get('discovery',{}).get('models',[]) if model.get('category')=='Image generation / component']
            if image_models:domain_tables+='<p class="meta">Discovered image weights: '+', '.join(esc(model['name']) for model in image_models)+'. Components do not receive standalone scores.</p>'
        else:
            description={'coding':'Python code tracing and targeted Python/SQL debugging. Answers are graded against fixed expected results; generated code is never executed.', 'vision':'Image color, object counting and spatial relationships using actual image inputs.', 'audio':'Listening comprehension and speech synthesis are measured separately below. Speech output is transcribed with a local CPU Whisper evaluator; case, punctuation and common digit/number-word spellings are normalized; changed or omitted words fail. This measures intelligibility, not voice naturalness.'}
            domain_tables+='<p>'+description[name]+'</p>'
            groups=[('Listening','audio'),('Speech output','speech')] if name=='audio' else [(None,None)]
            for subtitle,kind in groups:
                subset=data
                if kind:subset={**data,'tasks':[task for task in data['tasks'] if task.get('kind')==kind]}
                stats=domain_sections.comparisons(subset,name)
                if subtitle:domain_tables+='<h3>'+subtitle+'</h3>'
                if not stats:
                    domain_tables+='<p>No applicable benchmark results.</p>';continue
                domain_tables+='<div class="scroll"><table id="domain-'+name+('-'+kind if kind else '')+'"><thead><tr><th>Model</th><th>Task success</th><th>Speed</th><th>Quality</th></tr></thead><tbody>'
                for stat in stats:
                    speed=f"{stat['seconds']:.3f} s" if stat['seconds'] is not None else '—'
                    domain_tables+='<tr><td>'+esc(stat['model'])+'</td><td>'+percent(stat['success'])+'<small>'+esc(f"{stat['passed']}/{stat['expected']} passed · {stat['errors']} errors")+'</small></td><td>'+speed+'</td><td>'+percent(stat['quality'])+'</td></tr>'
                domain_tables+='</tbody></table></div>'
            domain_tables+='<p class="meta">Quality is difficulty-weighted success for this section only; speed is median latency of requests without runtime errors. Scores are separate from the overall rating.</p>'
        domain_tables+='</section>'
    standard=''
    inventory_note=('<p class="meta">Inventory refreshed: '+esc(data['discovery_updated'])+'. Benchmark scores retain their original evaluation dates.</p>') if data.get('discovery_updated') else ''
    if data.get('engine'):
        standard='<p class="meta">Evaluation engine: '+esc(data['engine'])+'. Every task score comes from EvalScope reviews, including registered local skill datasets. Standard datasets are sampled; overlap is workload-specific.</p>'
    legend=' '.join('<span>'+esc(icon)+' '+esc(cap.title())+'</span>' for cap,icon in ICONS.items())
    breakdown='<table><thead><tr><th>Model</th><th>Skill</th><th>Passed</th><th>Attempted</th><th>Weighted quality</th></tr></thead><tbody>'
    for row in rows:
        for cap,stat in row['skill_scores'].items():
            breakdown+='<tr><td>'+esc(row['model'])+'</td><td>'+esc(cap)+'</td><td>'+esc(f"{stat['passed']}/{stat['expected']}")+'</td><td>'+esc(stat['completed'])+'</td><td>'+percent(stat['percent'])+'</td></tr>'
    breakdown+='</tbody></table>'
    evidence=''
    taskmap={t['id']:t for t in data['tasks']}
    for result in data['results']:
        task=taskmap[result['task']]
        safe_task={k:v for k,v in task.items() if k!='image_b64'}
        media='<img width="360" height="240" alt="Benchmark image" src="data:image/png;base64,'+esc(task['image_b64'])+'">' if task.get('image_b64') else ''
        if task.get('asset') and task['kind']=='audio':
            audio=(ROOT/'fixtures'/task['asset']).read_bytes()
            if hashlib.sha256(audio).hexdigest()==task.get('asset_sha256'):
                media='<audio controls preload="none" aria-label="Benchmark recording" src="data:audio/wav;base64,'+base64.b64encode(audio).decode()+'"></audio>'
            else:
                media='<p>Original audio fixture unavailable: checksum mismatch. Current audio was not used for this saved result.</p>'
        if result.get('generated_audio_b64'):media+='<audio controls preload="none" aria-label="Generated speech" src="data:audio/wav;base64,'+esc(result['generated_audio_b64'])+'"></audio>'
        result={k:v for k,v in result.items() if k!='generated_audio_b64'}
        outcome='error' if result.get('error') else 'passed' if result['points']>0 else 'failed'
        search=' '.join([result['model'],result['task'],task.get('category','')]).lower()
        evidence+='<details data-outcome="'+outcome+'" data-search="'+esc(search)+'"><summary>'+esc(f"{result['model']} · {result['task']} · repeat {result['repeat']+1} · {result['points']}/{result['level']}")+'</summary>'+media+'<pre>'+esc(json.dumps({'task':safe_task,'result':result},indent=2,ensure_ascii=False))+'</pre></details>'
    insights=report_insights.render(data,rows)
    radar_start=insights.index('<section id="radar">')
    radar_end=insights.index('</section>',radar_start)+len('</section>')
    radar=insights[radar_start:radar_end]
    insight_cards=insights[:radar_start]
    insight_details=insights[radar_end:]
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ModelPrune report</title><style>
    :root{color-scheme:dark}*{box-sizing:border-box}body{background:#101621;color:#e1e8f5;font:15px system-ui;margin:0 auto;max-width:1400px;padding:28px}h1{font-size:36px;margin:0}h2{font-size:21px;margin-top:32px}p{line-height:1.6;color:#b9c7df}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:15px 10px;text-align:left;border-bottom:1px solid #334057;white-space:nowrap}th{color:#8ee8bf;font-size:12px;text-transform:uppercase;letter-spacing:.04em}small{display:block;font-size:11px;font-weight:400;color:#93a5bf;margin-top:5px}.icons{white-space:nowrap}.skill{display:inline-flex;align-items:center;justify-content:center;width:29px;height:30px;font-size:19px;margin:1px;border-radius:6px;border-bottom:3px solid #738099}.skill.passed{background:#15372e;border-color:#75deb5}.skill.mixed{background:#3b321b;border-color:#e6bc63}.skill.failed{background:#3d222d;border-color:#e88c98}.skill.untested{opacity:.5;border-style:dashed}.rating{font-size:20px;font-weight:700;color:#8ee8bf}.rating small:first-child{display:inline;margin-left:2px}.legend{display:flex;flex-wrap:wrap;gap:18px;color:#a8b8ce;font-size:13px;margin-top:18px}article,details{background:#192333;border:1px solid #334057;border-radius:9px;padding:14px;margin:10px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}a{color:#8ee8bf}.overlap-tag{margin:7px 0;padding:0;border:0;background:none;max-width:360px;white-space:normal}.overlap-tag summary{display:inline-block;font-size:11px;padding:4px 9px;border-radius:12px;border:1px solid #52637e;color:#b9c7df;list-style:none}.overlap-tag.replaceable summary{color:#f0b66c;border-color:#8b663a;background:#392d1e}.overlap-tag.tradeoff summary{color:#8bb9ff;border-color:#496a99;background:#1d2b42}.overlap-tag p{font-size:12px;margin:8px 0;max-width:340px}.overlap-tag summary:focus-visible{outline:2px solid #8ee8bf;outline-offset:2px}.badge{font-size:12px;margin-left:16px;color:#8ee8bf}.path{white-space:normal;overflow-wrap:anywhere;max-width:360px}.meta{font-size:12px;color:#8396b1}@media(max-width:700px){body{padding:14px}th,td{padding:12px 8px}}
    '''+report_insights.CSS+report_control.CSS+'''</style><h1>ModelPrune</h1><p>Local models. Measured skills. Clear comparisons.</p>'''
    page+='<p class="meta">'+esc(data['created'])+' · Ollama '+esc(data.get('ollama_version'))+' · '+esc(len(data['results'])+len(data.get('image_benchmark',{}).get('results',[])))+' evaluations'+'</p>'+report_control.render(data)+inventory_note+'<nav aria-label="Benchmark sections">__REPORT_NAV__</nav>'+standard+radar+insight_cards+tables+'<p class="meta">Model tags: Replaceable = a strictly higher-rated model covers all skills; Context tradeoff = less advertised context; Remote tradeoff = network-dependent replacement. Untagged models have no supported replacement. Click a tag for the reason. Suggestions apply only to tested workloads; nothing is deleted.</p>'+insight_details+domain_tables+'<div class="legend">'+legend+'</div><p class="meta">Skill icons: green = all passed; amber = some passed; red = none passed; dashed = incomplete or untested. Hover for results. Speed is median seconds per request; lower is faster.</p>'
    isolated=data.get('protocol')=='chat-isolated-v3' and bool(data['results']) and all(r.get('isolation',{}).get('verified') for r in data['results'])
    page+='<p class="meta">'+('Isolated Ollama run: other locally loaded Ollama models stopped; /api/ps checked around every task. Remote server isolation is not controlled.' if isolated else 'No benchmark has been run yet.' if not data['results'] else 'Legacy or unverified isolation: rerun with the current benchmark protocol before trusting comparisons.')+'</p>'
    page+='<details><summary>How the rating works</summary><p>Overall = (80% skill quality + 20% speed) × skill coverage. Quality averages the difficulty-weighted success of each measured skill equally. Speed is relative to peers with the same skills and execution location (local or remote). Remote latency includes network/provider time; hardware metadata describes this computer. Coverage is the fraction of declared skills with all scheduled tests attempted. Native skill failures and truncations earn zero; built-in suites use their published EvalScope grading. Unknown skills have zero coverage and prevent overlap recommendations. Task success is the unweighted pass rate over all scheduled tasks. Different skill profiles have different tests, so overall ratings are workload-specific.</p><p>Three levels test coding, speech synthesis, text completion, native decisions, visual perception, spoken audio understanding, tool selection/arguments, and reasoning with thinking enabled. Thinking tasks require both a correct answer and nonempty thinking output; this does not independently verify the reasoning trace. Tool calls are inspected, never executed. Audio uses bundled neural English speech with deliberate pacing and pauses and vision uses deterministic image fixtures. Declared capabilities do not guarantee quality. Long-context capacity, open-ended creative quality and real-world generalization are not established.</p></details>'
    discovered=data.get('discovery',{})
    benchmarked_names={row['model'] for row in rows}
    image_names={r['model'] for r in data.get('image_benchmark',{}).get('results',[])}
    other_models=[model for model in discovered.get('models',[]) if (model.get('source')!='Ollama' or model['name'] not in benchmarked_names) and model['name'] not in image_names]
    if other_models:
        page+='<h2 id="other-models">Other installed models</h2><p>Additional discovered entries have no benchmark score. Ollama language/audio models and explicitly run ComfyUI image checkpoints have adapters. Other weights, components and embedding suites without applicable suites have no score. Discovery does not load models or run model code.</p><div class="scroll"><table><thead><tr><th>Model</th><th>Source</th><th>Category</th><th>Size</th><th>Status</th></tr></thead><tbody>'
        for model in other_models:
            page+='<tr><td title="'+esc(model.get('path'))+'">'+esc(model['name'])+('<small>Aliases: '+', '.join(esc(a['name']) for a in model.get('aliases',[]))+'</small>' if model.get('aliases') else '')+'<small class="path">'+esc(model.get('path'))+'</small></td><td>'+esc(model['source'])+'</td><td>'+esc(model.get('category'))+'</td><td>'+esc(round(model.get('size',0)/1e9,2))+' GB</td><td>'+esc(model['status'])+'</td></tr>'
        page+='</tbody></table></div>'
    if discovered:
        page+='<details><summary>Discovery coverage</summary><p>'+esc(discovered.get('scope'))+'</p><pre>'+esc(json.dumps({key:discovered.get(key) for key in ['roots','entries_scanned','limited','warnings']},indent=2))+'</pre></details>'
    if data.get('evaluation_batches'):
        page+='<details><summary>Evaluation dates and execution locations</summary><p>Local scores are retained from the previous run; the remote models were evaluated separately. Remote latency includes network and provider time. Server hardware and remote co-tenancy are not measured.</p><pre>'+esc(json.dumps(data['evaluation_batches'],indent=2))+'</pre></details>'
    if data.get('engine'):
        page+='<details><summary>EvalScope suites and scoring provenance</summary><p>All main tables, ratings and overlap suggestions use scores imported from EvalScope reviews. Standard benchmark samples have weight 1; local multilevel fixtures use their stated level as weight. Coding is shown as its own measured skill for completion models. The standard sample limit is '+esc(data.get('standard_limit'))+' per subset. These bounded workloads do not establish general capability or definitive deletion advice.</p><pre>'+esc(json.dumps([{'model':r['model'],'suite':r['suite'],'source':r['source'],'evaluation':r['data'].get('execution_summary')} for r in data.get('engine_reports',[])],indent=2))+'</pre></details>'

    if data.get('invalidated_attempts'):
        page+='<details><summary>Excluded attempts ('+esc(len(data['invalidated_attempts']))+')</summary><p>These attempts were excluded from scores and timing, and their tasks were rerun.</p><pre>'+esc(json.dumps(data['invalidated_attempts'],indent=2,ensure_ascii=False))+'</pre></details>'
    page+='<details><summary>Per-skill scores</summary><div class="scroll">'+breakdown+'</div></details><details><summary>Configuration and environment</summary><pre>'+esc(json.dumps({k:data[k] for k in ['config','host','hardware']},indent=2))+'</pre><p>Advertised context and logical disk size come from Ollama. Shared layers affect reclaimable space. Timings include model loading and may vary with other workloads. The isolated runner stops all loaded Ollama models before each model, checks for other loaded models around every task, and unloads the tested model afterward. Non-Ollama system activity is not controlled. MoE parameter size is the total parameter count; expert counts come from metadata, not an inferred active-parameter estimate. Audio uses the OpenAI-compatible endpoint and its native context defaults; other tasks use the configured context where supported. Repeats of fixed fixtures measure consistency, not independent generalization.</p></details><h2 id="evidence">Task evidence</h2><div class="report-tools"><label>Find model or task <input id="evidence-search" type="search" placeholder="Model, task or category"></label><label>Outcome <select id="evidence-state"><option value="all">All outcomes</option><option value="passed">Passed</option><option value="failed">Incorrect answers</option><option value="error">Runtime / output-limit errors</option></select></label><span id="evidence-count" aria-live="polite"></span></div><div id="task-evidence">'+evidence+'</div><script>'+report_insights.SCRIPT+'</script><script>'+report_control.SCRIPT+'</script></html>'
    sections=[('radar','Radar'),('models-generative','Generative models'),('models-decision','Decision models'),('benchmarks','Benchmarks'),('performance','Performance'),('calibration','Confidence'),('coding','Coding'),('vision','Vision'),('image-generation','Image generation'),('audio','Audio'),('other-models','Other installed models'),('evidence','Task evidence')]
    sections=[(key,label) for key,label in sections if 'id="'+key+'"' in page]
    sections.sort(key=lambda item:page.index('id="'+item[0]+'"'))
    return page.replace('__REPORT_NAV__',' · '.join('<a href="#'+key+'">'+esc(label)+'</a>' for key,label in sections))
