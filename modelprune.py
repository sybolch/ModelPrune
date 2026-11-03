#!/usr/bin/env python3
"""ModelPrune: dependency-free, local Ollama evaluation. Never executes model output."""
import argparse
import csv
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import skill_tasks
import isolation
import discovery
import model_aliases

VERSION = '1.0.0'
PROTOCOL = 'chat-isolated-v3'
ROOT = Path(__file__).resolve().parent


def api(host, path, payload=None, timeout=180):
    req = urllib.request.Request(host.rstrip('/') + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.load(response)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code}: {e.read().decode()[:500]}') from e


def inventory(host,timeout=15):
    models = api(host, '/api/tags',timeout=timeout)['models']
    for model in models:
        try:
            info = api(host, '/api/show', {'model': model['name']},timeout=timeout)
            model['capabilities'] = info.get('capabilities', [])
            model['weight_identity']=model_aliases.identity(info)
            model['runtime_parameters']=info.get('parameters','')
            context_override=re.search(r'^num_ctx\s+(\d+)',model['runtime_parameters'],re.M)
            model['context_override']=int(context_override[1]) if context_override else None
            metadata=info.get('model_info',{})
            model['architecture']=metadata.get('general.architecture')
            model['expert_count']=max((v for k,v in metadata.items() if k.endswith('.expert_count') and isinstance(v,int)),default=0)
            model['experts_used']=max((v for k,v in metadata.items() if k.endswith('.expert_used_count') and isinstance(v,int)),default=0)
            model['architecture_type']='MoE' if model['expert_count']>0 else 'Dense'
            model['details'] = info.get('details', model.get('details', {}))
            model['context'] = max((v for k, v in info.get('model_info', {}).items()
                                    if k.endswith('.context_length') and isinstance(v, int)), default=None)
            model['parameters'] = info.get('model_info', {}).get('general.parameter_count')
            model['remote'] = bool(info.get('remote_host') or info.get('remote_model') or model.get('remote_host'))
        except (OSError, ValueError, RuntimeError) as e:
            model['inspection_error'] = str(e)
            model['capabilities'] = []
    return model_aliases.annotate(models)


def suite():
    tasks = []
    def choice(id, level, category, state, question, options, answer):
        tasks.append(dict(id=id, level=level, category=category, kind='decision',
                          state=state, prompt=question, options=options, expected=answer))
    choice('route-1',1,'routing','I was charged twice. Please refund the extra payment.',
           'Which team handles this ticket?',{'billing':'Payments and refunds','technical':'Software errors','account':'Account access'},'billing')
    choice('route-2',2,'routing','The payment succeeded. My password reset link always says expired. I need to log in.',
           'Route by the unresolved issue.',{'billing':'Payment issue','technical':'Checkout bug','account':'Login or password reset'},'account')
    choice('route-3',3,'routing','Policy: confirmed data disclosure goes to security before any billing issue. Ticket: I see another customer’s address on my invoice and the total is wrong.',
           'Which team has priority under the policy?',{'billing':'Invoice amount errors','security':'Disclosure of another customer’s data','account':'Password resets'},'security')
    choice('policy-1',1,'policy','Refund policy: eligible within 30 days. Purchase was 12 days ago.',
           'Is the purchase eligible?',{'yes':'Eligible','no':'Ineligible'},'yes')
    choice('policy-2',2,'policy','Refunds require age <=30 days AND an unused item. An unused item was bought exactly 30 days ago.',
           'Apply the rule exactly.',{'yes':'Eligible','no':'Ineligible','unknown':'Insufficient information'},'yes')
    choice('policy-3',3,'policy','Refund requires purchase <=30 days and unused item. Clearance items are excluded unless defective. Item: 20 days old, unused, clearance, defective.',
           'Apply all rules and exceptions.',{'yes':'Eligible','no':'Ineligible','unknown':'Insufficient information'},'yes')
    choice('logic-1',1,'reasoning','All zips are blue. This object is a zip.',
           'Must this object be blue?',{'yes':'Yes','no':'No','unknown':'Cannot determine'},'yes')
    choice('logic-2',2,'reasoning','All zips are blue. Some blue things are round. This object is a zip.',
           'Must this object be round?',{'yes':'Yes','no':'Definitely not','unknown':'Cannot determine'},'unknown')
    choice('logic-3',3,'reasoning','Exactly one of A, B, C is true. A says B is false. B says C is true. C says A is false.',
           'Which assignment satisfies all statements?',{'a':'Only A is true','b':'Only B is true','c':'Only C is true','none':'No assignment'},'a')
    def gen(id, level, category, prompt, expected):
        tasks.append(dict(id=id, level=level, category=category, kind='generation', prompt=prompt, expected=expected))
    gen('math-1',1,'arithmetic','Compute 17 * 6. Return JSON {"answer": integer}.',{'answer':102})
    gen('math-2',2,'arithmetic','A basket has 3 items at 19 each. Apply a 10% discount to the subtotal, then add 5 shipping. Return JSON {"answer": number}.',{'answer':56.3})
    gen('math-3',3,'arithmetic','A tank starts with 120 liters. Remove 25%, add 18 liters, then remove one third of the current amount. Return JSON {"answer": number}.',{'answer':72})
    gen('extract-1',1,'extraction','From "Mira ordered 4 red mugs", return JSON with exactly keys name (string) and count (integer).',{'name':'Mira','count':4})
    gen('extract-2',2,'extraction','Records: a paid 12; b pending 9; c paid 7. Sum only paid values and list their IDs in original order. Return JSON {"total":number,"ids":[strings]}.',{'total':19,'ids':['a','c']})
    gen('extract-3',3,'extraction','Use the latest record per ID by numeric revision, then sum values whose latest status is paid. Records: a rev1 paid 12; b rev2 paid 9; a rev3 void 12; c rev1 paid 7; b rev1 pending 9. Return JSON {"total":number,"ids":[strings sorted ascending]}.',{'total':16,'ids':['b','c']})
    gen('code-1',1,'code-tracing','Trace Python: xs=[1,2,3]; result=[x*2 for x in xs if x>1]. Return JSON {"result":array}.',{'result':[4,6]})
    gen('code-2',2,'code-tracing','Trace Python: xs=[1,2]; ys=xs; ys.append(3); zs=xs[:]; zs.append(4). Return JSON {"xs":array,"zs":array}.',{'xs':[1,2,3],'zs':[1,2,3,4]})
    gen('code-3',3,'code-tracing','Trace Python: funcs=[lambda: i for i in range(3)]; fixed=[lambda i=i: i for i in range(3)]; a=[f() for f in funcs]; b=[f() for f in fixed]. Return JSON {"a":array,"b":array}.',{'a':[2,2,2],'b':[0,1,2]})
    gen('debug-1',1,'code-debugging','Fix Python: def is_even(n): return n % 2 == 1. Return JSON {"operator":string,"value":integer} specifying the comparison operator and right operand for n % 2.',{'operator':'==','value':0})
    gen('debug-2',2,'code-debugging','A Python binary search over inclusive bounds has: lo=0; hi=len(xs)-1; while lo < hi: mid=(lo+hi)//2; if xs[mid]==target: return mid; elif xs[mid]<target: lo=mid+1; else: hi=mid-1. Return JSON {"loop_operator":string,"missing_return":integer}. Fix the loop so a one-element interval is searched; return -1 if absent.',{'loop_operator':'<=','missing_return':-1})
    gen('debug-3',3,'code-debugging','A SQL query should count ALL orders per customer, including customers with zero orders. It uses customers c LEFT JOIN orders o ON o.customer_id=c.id, GROUP BY c.id, and COUNT(*). Return JSON {"aggregate":string,"join":string} with the corrected aggregate expression and required join type. Use o.id as the non-null order identifier.',{'aggregate':'COUNT(o.id)','join':'LEFT JOIN'})
    return tasks + skill_tasks.tasks()


def equal(a,b):
    if isinstance(b, bool): return type(a) is bool and a == b
    if isinstance(b,(int,float)):
        return type(a) in (int,float) and abs(a-b) < 1e-6
    if isinstance(b,dict): return isinstance(a,dict) and a.keys()==b.keys() and all(equal(a[k],v) for k,v in b.items())
    if isinstance(b,list): return isinstance(a,list) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return type(a) is type(b) and a==b


def skill_equal(answer,expected,kind):
    def normalize(value):
        if isinstance(value,str): return value.strip().casefold()
        if isinstance(value,dict): return {k:normalize(v) for k,v in value.items()}
        if isinstance(value,list): return [normalize(v) for v in value]
        return value
    if kind=='audio': return equal(normalize(answer),normalize(expected))
    if kind=='tools' and isinstance(answer,dict):
        answer=dict(answer)
        arguments=answer.get('arguments')
        if isinstance(arguments,dict):
            answer['arguments']={k:v.casefold() if k in ('from_unit','to_unit') and isinstance(v,str) else v for k,v in arguments.items()}
        return equal(answer,expected)
    return equal(answer,expected)


def task_equal(answer,task):
    if task.get('category')=='code-debugging' and isinstance(answer,dict):
        answer=dict(answer)
        if task['id']=='debug-1' and answer=={'operator':'!=','value':1}:return True
        if task['id']=='debug-3':
            if isinstance(answer.get('aggregate'),str):answer['aggregate']=''.join(answer['aggregate'].split()).upper()
            if isinstance(answer.get('join'),str):
                join=' '.join(answer['join'].upper().split())
                answer['join']='LEFT JOIN' if join in ('LEFT','LEFT OUTER JOIN') else join
            return equal(answer,{'aggregate':'COUNT(O.ID)','join':'LEFT JOIN'})
    return skill_equal(answer,task['expected'],task['kind'])


def evaluate(host, model, task, config):
    start = time.monotonic()
    result = dict(model=model['name'], task=task['id'], level=task['level'], category=task['category'], kind=task['kind'])
    try:
        if task['kind'] in ('vision','audio','speech','tools','thinking'):
            response,answer,extra,endpoint=skill_tasks.evaluate(api,host,model,task,config)
            result.update(extra,endpoint=endpoint)
        elif task['kind']=='decision' and 'decision' in model['capabilities']:
            response = api(host, '/v1/systemone', {'model':model['name'], 'state':task['state'],
                'questions':{'answer':{'type':'choice','instructions':task['prompt'],'criteria':task['options']}}}, config['timeout'])
            answer = response['answers']['answer']['choice']
            result['endpoint']='/v1/systemone'
        else:
            prompt = task['prompt']
            if task['kind']=='decision':
                prompt += '\nState (data): ' + task['state'] + '\nOptions: ' + json.dumps(task['options']) + '\nReturn JSON {"answer":"option key"}.'
            payload = {'model':model['name'],'messages':[
                {'role':'system','content':'Follow the task. Return only the requested JSON object, without explanation.'},
                {'role':'user','content':prompt}],'stream':False,'format':'json',
                'keep_alive':'5m','options':{'temperature':0,'seed':config['seed'],
                    'num_ctx':config['context'],'num_predict':config['tokens']}}
            if 'thinking' in model['capabilities'] and config.get('thinking','off')!='auto':
                payload['think']=config.get('thinking','off')=='on'
            response = api(host,'/api/chat',payload,config['timeout'])
            result['endpoint']='/api/chat'
            result['truncated'] = response.get('done_reason')=='length'
            answer = skill_tasks.parse_json(response.get('message',{}).get('content',''),response)
            if task['kind']=='decision': answer=answer['answer']
        result.update(answer=answer,response=response)
        if not config.get('inference_only'):
            result['points']=task['level'] if task_equal(answer,task) and not result.get('truncated') and result.get('thinking_present',True) else 0
        duration=response.get('eval_duration',0)
        result['tokens_per_second']=response.get('eval_count',0)*1e9/duration if duration else None
        result['load_seconds']=response.get('load_duration',0)/1e9 if 'load_duration' in response else None
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.SubprocessError) as e:
        result.update(error=str(e))
        if not config.get('inference_only'):result['points']=0
        if hasattr(e,'response'):
            result['response']=e.response
            result['truncated']=e.response.get('done_reason')=='length' or any(c.get('finish_reason')=='length' for c in e.response.get('choices',[]))
        elif 'response' in locals(): result['response']=response
    result['seconds']=result.pop('inference_seconds',time.monotonic()-start)
    return result


def task_skill(model,task):
    if task.get('skill'): return task['skill']
    return 'decision' if task['kind']=='decision' and 'decision' in model['capabilities'] else 'completion'


def applicable(model,task):
    if task.get('skill'): return task['skill'] in model['capabilities']
    return 'completion' in model['capabilities'] or (task['kind']=='decision' and 'decision' in model['capabilities'])


def aggregate(data):
    rows=[]
    for model in data['models']:
        runs=[r for r in data['results'] if r['model']==model['name']]
        tasks=[t for t in data['tasks'] if applicable(model,t)]
        taskmap={t['id']:t for t in tasks}
        possible=sum(t['level'] for t in tasks)*data['config']['repeats']
        score=sum(r['points'] for r in runs)
        times=[r['seconds'] for r in runs if not r.get('error')]
        speeds=[r['tokens_per_second'] for r in runs if r.get('tokens_per_second')]
        skill_scores={}
        for cap in model['capabilities']:
            selected=[t for t in tasks if task_skill(model,t)==cap]
            evidence=[r for r in runs if r['task'] in taskmap and task_skill(model,taskmap[r['task']])==cap]
            maximum=sum(t['level'] for t in selected)*data['config']['repeats']
            expected=len(selected)*data['config']['repeats']
            skill_scores[cap]=dict(expected=expected,completed=len(evidence),passed=sum(r['points']>0 for r in evidence),
                errors=sum(bool(r.get('error')) for r in evidence),
                median_seconds=statistics.median(r['seconds'] for r in evidence) if evidence else None,
                percent=100*sum(r['points'] for r in evidence)/maximum if maximum else None)
        expected=len(tasks)*data['config']['repeats']
        coverage=sum(bool(s['expected']) and s['completed']==s['expected'] for s in skill_scores.values())/len(skill_scores) if skill_scores else 0
        quality=sum(s['percent'] or 0 for s in skill_scores.values())/len(skill_scores) if skill_scores else 0
        rows.append(dict(model=model['name'],model_type='Decision' if 'decision' in model['capabilities'] else 'Generative',
            aliases=model.get('aliases',[]),benchmark_registration=model.get('benchmark_registration'),remote=bool(model.get('remote')),size_gb=round(model['size']/1e9,2),architecture=model.get('architecture'),architecture_type=model.get('architecture_type','Unknown'),
            expert_count=model.get('expert_count'),experts_used=model.get('experts_used'),parameters=model.get('details',{}).get('parameter_size','?'),
            quantization=model.get('details',{}).get('quantization_level','?'),context=model.get('context'),capabilities=model['capabilities'],
            points=score,possible=possible,percent=round(100*score/possible,1) if possible else None,
            success_rate=round(100*sum(r['points']>0 for r in runs)/expected,1) if expected else None,
            completed=len(runs),expected=expected,errors=sum(bool(r.get('error')) for r in runs),
            median_seconds=round(statistics.median(times),4) if times else None,
            tokens_per_second=round(statistics.median(speeds),2) if speeds else None,
            skill_scores=skill_scores,skill_coverage=coverage,quality=quality))
    for row in rows:
        peers=[r['median_seconds'] for r in rows if set(r['capabilities'])==set(row['capabilities']) and r.get('remote',False)==row.get('remote',False) and r['median_seconds']]
        row['speed_score']=100*min(peers)/row['median_seconds'] if peers and row['median_seconds'] else 0
        row['rating']=round((0.8*row['quality']+0.2*row['speed_score'])*row['skill_coverage'],1) if row['completed'] else None
    return rows


def recommendations(data, rows):
    """A strictly higher overall rating can replace only a subset of its skills."""
    decisions=[]
    byname={model['name']:model for model in data['models']}
    def complete(row):
        evidence=[result for result in data['results'] if result['model']==row['model']]
        isolation_valid=all(result.get('isolation',{}).get('verified',True) for result in evidence)
        return (isolation_valid and row['expected']>0 and row['completed']==row['expected']
                and row['skill_coverage']==1 and row['rating'] is not None)
    for target in rows:
        own=set(target['capabilities'])
        covering=[peer for peer in rows if peer is not target
                  and own.issubset(peer['capabilities'])]
        candidates=[peer for peer in covering if complete(target) and complete(peer)
                    and peer['rating']>target['rating']]
        sufficient_context=[peer for peer in candidates
            if (peer.get('context') or 0)>=(target.get('context') or 0)]
        pool=sufficient_context or candidates
        replacement=max(pool,key=lambda row:(row['rating'],-row['size_gb'])) if pool else None
        if replacement:
            extra=sorted(set(replacement['capabilities'])-own)
            reason=(f"{replacement['model']} rates higher ({replacement['rating']:.1f} vs {target['rating']:.1f}/100) "
                    f"and covers all declared skills"+(' plus '+', '.join(extra) if extra else '')+'.')
            if sufficient_context:
                status='Unnecessary for tested workloads'
            else:
                status='Workload overlap / context tradeoff'
                reason+=f" Advertised context falls from {target.get('context')} to {replacement.get('context')}; retain this model if you need the longer context."
            if replacement.get('remote') and not target.get('remote'):
                status='Workload overlap / remote execution tradeoff'
                reason+=' Replacement requires remote inference and network access; retain the local model if you need offline execution.'
            if replacement['size_gb']>target['size_gb']:
                reason+=f" Replacement uses more logical disk space ({replacement['size_gb']} vs {target['size_gb']} GB)."
            if replacement['median_seconds'] is not None and target['median_seconds'] is not None and replacement['median_seconds']>target['median_seconds']:
                reason+=' Replacement has higher median request latency.'
            reason+=' Ratings include failed tasks; this is a benchmark-based recommendation, not proof of equivalence on every individual task.'
        else:
            status='Keep / insufficient evidence'
            reason=('Incomplete skill evaluation.' if not complete(target) else
                    'No fully tested model with a strictly higher overall rating covers every declared skill.')
        decisions.append(dict(model=target['model'],status=status,
            replacement=replacement['model'] if replacement else None,reason=reason,skills=sorted(own),
            covering_skill_peers=[peer['model'] for peer in covering],
            same_skill_peers=[peer['model'] for peer in rows if peer is not target and set(peer['capabilities'])==own],
            skill_differences=[dict(model=peer['model'],only_this_model=sorted(own-set(peer['capabilities'])),
                only_other_model=sorted(set(peer['capabilities'])-own)) for peer in rows
                if peer is not target and set(peer['capabilities'])!=own]))
    return decisions


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    temp.replace(path)


def installed_report_view(data):
    """Filter presentation by the latest inventory; never discard historical evidence."""
    inventory=data.get('discovery')
    if not inventory or 'models' not in inventory:return data
    current={model['name']:model for model in inventory['models'] if model.get('source')=='Ollama'}
    view=copy.deepcopy(data);view['models']=[];mapping={}
    history={model['name']:model for model in data['models']}
    for canonical,found in current.items():
        registrations=found.get('registrations',[{'name':canonical,'digest':found.get('digest')}])
        registrations=sorted(registrations,key=lambda r:r['name']!=canonical)
        chosen=None
        for registration in registrations:
            old=history.get(registration['name'])
            if old is not None and not(old.get('digest') and registration.get('digest') and old['digest']!=registration['digest']):
                chosen=copy.deepcopy(old);mapping[old['name']]=canonical;break
        if chosen is None and found.get('weight_identity'):
            prior=next((old for old in data['models'] if old.get('weight_identity')==found['weight_identity']),None)
            if prior:
                chosen=copy.deepcopy(prior);mapping[prior['name']]=canonical
        if chosen is None:continue
        if chosen['name']!=canonical:chosen['benchmark_registration']=chosen['name']
        chosen.update(name=canonical,aliases=found.get('aliases',[]))
        view['models'].append(chosen)
    names=set(mapping)
    view['results']=[{**result,'model':mapping[result['model']]} for result in data['results'] if result['model'] in names]
    found_images={model['name'] for model in inventory['models'] if model.get('source')!='Ollama'}
    if view.get('image_benchmark'):
        view['image_benchmark']['results']=[r for r in view['image_benchmark']['results'] if r['model'] in found_images]
    visible=names|{r['model'] for r in view.get('image_benchmark',{}).get('results',[])}
    view['engine_reports']=[{**r,'model':mapping.get(r['model'],r['model'])} for r in data.get('engine_reports',[]) if r['model'] in mapping or r['model'] in visible]
    view['invalidated_attempts']=[r for r in data.get('invalidated_attempts',[]) if r['model'] in names]
    return view


def report(data,destination):
    data=installed_report_view(data)
    if data.get('engine') and any(result.get('score_engine')!='EvalScope' for result in data['results']+data.get('image_benchmark',{}).get('results',[])):
        raise RuntimeError('Unified report refuses scores not imported from EvalScope reviews')
    import report_ui
    destination.mkdir(parents=True,exist_ok=True)
    rows=aggregate(data)
    decisions=recommendations(data,rows)
    fields=['model','model_type','parameters','context','capabilities','success_rate','median_seconds','rating']
    with (destination/'comparison.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    (destination/'report.html').write_text(report_ui.render(data,rows,decisions))
    save(destination/'summary.json',{'engine':data.get('engine'),'standard_limit':data.get('standard_limit'),'comparison':rows,'recommendations':decisions,'discovery':data.get('discovery'),'image_benchmark':data.get('image_benchmark'),'evalscope':data.get('evalscope')})
    if data.get('discovery'): save(destination/'discovery.json',data['discovery'])
    print('\nModel                           Success   Median s   Rating')
    for row in rows:
        print(f"{row['model']:<30} {str(row['success_rate']):>7}% {str(row['median_seconds']):>9} {str(row['rating']):>8}")
    print('\n'+'\n'.join(d['model']+': '+d['status']+(' → '+d['replacement'] if d['replacement'] else '') for d in decisions))
    print(f'\nReport: {destination / "report.html"}')


def hardware():
    result={'platform':platform.platform(),'cpu':platform.processor(),'logical_cpus':os.cpu_count()}
    try:
        result['memory']=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','SwapTotal:')))
        result['gpu']=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'],text=True,timeout=5).strip()
    except (OSError,subprocess.SubprocessError): pass
    return result


def main():
    if len(sys.argv)>3 and sys.argv[1]=='--host' and sys.argv[3]=='run':
        import evalscope_run
        return evalscope_run.main(['--host',sys.argv[2]]+sys.argv[4:])
    if len(sys.argv)>1 and sys.argv[1]=='run':
        import evalscope_run
        return evalscope_run.main(sys.argv[2:])
    if len(sys.argv)>1 and sys.argv[1]=='evalscope':
        import evalscope_bridge
        return evalscope_bridge.main(sys.argv[2:])
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='ModelPrune '+VERSION)
    parser.add_argument('--host',default=os.environ.get('OLLAMA_HOST','http://127.0.0.1:11434'))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('evalscope',help='Standard benchmark backend; use evalscope plan/run --help')
    listing=sub.add_parser('list',help='Find installed models across local stores and model folders')
    listing.add_argument('--scan-path',action='append',type=Path,help='Additional model folder; may be repeated')
    listing.add_argument('--scan-limit',type=int,default=5_000_000)
    listing.add_argument('--json',action='store_true',help='Print full discovery JSON')
    listing.add_argument('--output',type=Path,help='Save discovery JSON')
    sub.add_parser('run',help='Run the unified EvalScope evaluation engine')
    rep=sub.add_parser('report',help='Regenerate HTML/CSV from saved evidence without Ollama')
    rep.add_argument('file',type=Path)
    rep.add_argument('--image-results',type=Path,help='Attach saved ComfyUI image benchmark results')
    rep.add_argument('--discovery',type=Path,help='Attach a fresh saved discovery inventory to this report')
    args=parser.parse_args()
    if args.command=='run':
        import evalscope_run
        return evalscope_run.main(['--host',args.host]+sys.argv[sys.argv.index('run')+1:])
    if args.command=='report':
        data=json.loads(args.file.read_text())
        if args.discovery: data['discovery']=json.loads(args.discovery.read_text())
        if args.image_results: data['image_benchmark']=json.loads(args.image_results.read_text())
        report(data,args.file.parent);return
    if getattr(args,'scan_limit',1)<1: parser.error('--scan-limit must be positive')
    if not args.host.startswith(('http://','https://')): args.host='http://'+args.host
    if args.command=='list':
        try: models=inventory(args.host)
        except (OSError,ValueError,RuntimeError) as error:
            models=[];print('Ollama unavailable: '+str(error),file=sys.stderr)
        found=discovery.scan(models,(args.scan_path or [])+discovery.default_roots(),args.scan_limit)
        if args.output: save(args.output,found)
        if args.json: print(json.dumps(found,indent=2,ensure_ascii=False))
        else:
            print(f"{'Model':48} {'Source':16} {'GB':>7}  Status")
            for model in found['models']:
                print(f"{model['name'][:48]:48} {model['source']:16} {model.get('size',0)/1e9:7.2f}  {model['status']}")
            print(f"\n{len(found['models'])} models found; {found['entries_scanned']} filesystem entries inspected.")
            for warning in found['warnings']: print('Discovery warning: '+warning,file=sys.stderr)
        return

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,RuntimeError) as error:
        print('ModelPrune: '+str(error),file=sys.stderr);sys.exit(1)
