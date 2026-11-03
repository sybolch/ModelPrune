"""Task-family comparisons independent of advertised runtime capabilities."""
import statistics

DOMAINS={'coding':'Coding','vision':'Vision','image-generation':'Image generation','audio':'Audio'}

def domain(task):
    if task.get('category') in ('code-tracing','code-debugging'):return 'coding'
    if task.get('kind')=='vision':return 'vision'
    if task.get('kind') in ('audio','speech'):return 'audio'
    if task.get('kind')=='image-generation':return 'image-generation'

def comparisons(data,name):
    tasks={t['id']:t for t in data['tasks'] if domain(t)==name}
    rows=[]
    for model in data['models']:
        caps=model['capabilities']
        selected={k:t for k,t in tasks.items() if (t.get('skill') in caps if t.get('skill') else 'completion' in caps)}
        if not selected:continue
        expected=len(selected)*data['config']['repeats']; possible=sum(t['level'] for t in selected.values())*data['config']['repeats']
        results=[r for r in data['results'] if r['model']==model['name'] and r['task'] in selected]
        times=[r['seconds'] for r in results if not r.get('error')]
        rows.append(dict(model=model['name'],passed=sum(r['points']>0 for r in results),expected=expected,completed=len(results),
          quality=100*sum(r['points'] for r in results)/possible,success=100*sum(r['points']>0 for r in results)/expected,
          seconds=statistics.median(times) if times else None,errors=sum(bool(r.get('error')) for r in results)))
    return sorted(rows,key=lambda r:(-r['quality'],r['seconds'] or float('inf')))
