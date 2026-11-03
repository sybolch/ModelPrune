#!/usr/bin/env python3
"""EvalScope backend for ModelPrune: standard suites with per-request Ollama isolation."""
import argparse,hashlib,json,os,shutil,statistics,subprocess,threading,time,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import modelprune as m
import isolation

SUITES={'boolq':{'skill':'decision / completion','description':'Reading comprehension; comparable across decision and text models'},
        'gsm8k':{'skill':'completion','description':'Multi-step arithmetic; zero-shot'},
        'ifeval':{'skill':'completion','description':'Verifiable instruction following'}}
GAPS={'coding':'Retain ModelPrune tracing/debugging; HumanEval/MBPP need a separately configured code sandbox.',
      'vision':'Retain ModelPrune image-input tests; EvalScope multimodal adapters/datasets not verified here.',
      'audio':'Retain ModelPrune listening/speech and local ASR grading.',
      'image-generation':'Retain ModelPrune ComfyUI workflow; not an OpenAI image endpoint.',
      'tools / thinking':'Retain native tool-call and dedicated thinking tests; standard text scores do not establish these skills.'}

def applicable(model,suite):
    caps=set(model.get('capabilities',[]))
    return (bool(caps&{'decision','completion'}) if suite=='boolq' else 'completion' in caps and 'decision' not in caps)

def command(executable,model,suite,proxy_url,destination,limit):
    decision='decision' in model['capabilities']
    config={'timeout':180,'retries':1,'stream':False}
    if not decision:
        config.update(temperature=0,max_tokens=1024,seed=42)
        if 'thinking' in model['capabilities']:config['reasoning_effort']='none'
    return [executable,'eval','--model',model['name'],'--eval-type','systemone_api' if decision else 'openai_api',
      '--api-url',proxy_url+'/v1','--api-key','EMPTY','--datasets',suite,'--dataset-hub','huggingface',
      '--dataset-args',json.dumps({suite:{'few_shot_num':0}}), '--generation-config',json.dumps(config),
      '--eval-batch-size','1','--limit',str(limit),'--seed','42','--work-dir',str(destination),'--no-timestamp','--collect-perf']

class Proxy:
    def __init__(self,host,model):
        self.host=host.rstrip('/');self.model=model;self.events=[];self.violations=[];self.lock=threading.Lock()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                with owner.lock:
                    started=time.monotonic();event={'path':self.path,'verified':False}
                    try:
                        if self.path not in ('/v1/chat/completions','/v1/systemone'):raise RuntimeError('Unexpected endpoint')
                        length=int(self.headers.get('Content-Length',0))
                        if not 0<length<=10_000_000:raise RuntimeError('Invalid request length')
                        content=self.rfile.read(length);payload=json.loads(content)
                        if payload.get('model')!=owner.model:raise RuntimeError('Unexpected requested model')
                        if payload.get('stream'):raise RuntimeError('Streaming disabled for isolation verification')
                        event['before']=isolation.stop_others(m.api,owner.host,keep=owner.model)
                        # Record hashes, not private request bodies; EvalScope owns raw sample evidence.
                        event['request_sha256']=hashlib.sha256(content).hexdigest()
                        request=urllib.request.Request(owner.host+self.path,data=content,headers={'Content-Type':'application/json'})
                        try:
                            with urllib.request.urlopen(request,timeout=190) as response:body=response.read();status=response.status
                        except urllib.error.HTTPError as error:body=error.read();status=error.code
                        event['after']=isolation.loaded(m.api,owner.host)
                        if any(name!=owner.model for name in event['after']):raise RuntimeError('Isolation violated during EvalScope request')
                        event.update(verified=True,status=status)
                        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
                    except Exception as error:
                        owner.violations.append(str(error));event['error']=str(error)
                        self.send_response(503);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'error':{'message':str(error),'type':'isolation_error'}}).encode())
                    finally:
                        event['seconds']=time.monotonic()-started;owner.events.append(event)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def __enter__(self):self.thread.start();return self
    @property
    def url(self):return 'http://127.0.0.1:'+str(self.server.server_port)
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join()

def report_files(folder):
    # EvalScope's versioned reports stay authoritative; preserve full objects and paths.
    reports=[]
    for path in sorted(Path(folder).rglob('*.json')):
        if 'reports' in path.parts:
            try:report=json.loads(path.read_text())
            except (OSError,ValueError):continue
            reports.append({'path':str(path.relative_to(folder)),'data':report})
    return reports

def summarize(entry):
    """Read schema-v2 primary metric semantics; never average unrelated metrics."""
    import math
    values=[]
    for item in entry.get('reports',[]):
        report=item['data']
        if report.get('schema_version')!=2 or report.get('dataset_name')!=entry.get('suite'):continue
        primary=report.get('primary_metric_identity')
        metric=next((x for x in report.get('metrics',[]) if x.get('identity')==primary),None)
        if not metric:continue
        score=metric.get('score');semantics=metric.get('semantics',{})
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score):continue
        execution=report.get('execution_summary',{})
        complete=execution.get('incomplete') is False and execution.get('errored')==0 and execution.get('succeeded',0)>0 and execution.get('succeeded')==execution.get('requested')
        values.append({'metric':semantics.get('display_name') or primary.get('name') or semantics.get('metric_name'),'score':score,
          'display_score':score*(semantics.get('display_multiplier') or 1),'unit':semantics.get('display_unit') or '',
          'direction':semantics.get('direction'),'samples':metric.get('num'),
          'complete':complete,'execution':execution,'source':item['path']})
    return values


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','run'])
    parser.add_argument('--host',default=os.environ.get('OLLAMA_HOST','http://127.0.0.1:11434'))
    parser.add_argument('--models',nargs='+');parser.add_argument('--datasets',nargs='+',choices=SUITES,default=list(SUITES))
    parser.add_argument('--limit',type=int,default=25,help='Samples per subset (pilot by default, not a full benchmark)')
    parser.add_argument('--output',type=Path);parser.add_argument('--executable',default=shutil.which('evalscope') or 'evalscope')
    args=parser.parse_args(argv)
    if args.limit<1:parser.error('--limit must be positive')
    version=subprocess.check_output([args.executable,'--version'],text=True,timeout=30).strip()
    models=m.inventory(args.host)
    if args.models:
        unknown=set(args.models)-{model['name'] for model in models}
        if unknown:parser.error('Models not installed: '+', '.join(sorted(unknown)))
        models=[model for model in models if model['name'] in args.models]
    jobs=[(model,suite) for model in models for suite in args.datasets if applicable(model,suite)]
    if not jobs:parser.error('No supported local model/suite pairs')
    plan={'engine':version,'created':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'limit_per_subset':args.limit,'seed':42,
          'datasets':SUITES,'coverage_gaps':GAPS,'models':models,'jobs':[{'model':model['name'],'suite':suite} for model,suite in jobs],
          'runs':[],'note':'Pilot subsets; do not use for model removal. Legacy scores are not mixed with standard suite metrics.'}
    if args.action=='plan':print(json.dumps(plan,indent=2));return
    if not args.output:parser.error('--output is required for run')
    if args.output.exists():parser.error('Choose a fresh output directory')
    args.output.mkdir(parents=True);manifest=args.output/'evalscope-results.json';m.save(manifest,plan)
    failure=False
    try:
        for index,(model,suite) in enumerate(jobs):
            destination=(args.output/f'{index+1:03d}-{suite}').resolve();destination.mkdir()
            entry={'model':model['name'],'suite':suite,'limit_per_subset':args.limit,'folder':str(destination.relative_to(args.output.resolve()))}
            print(f"EvalScope: {model['name']} · {suite} · up to {args.limit} samples/subset",flush=True)
            entry['isolation_start']=isolation.stop_others(m.api,args.host)
            try:
                with Proxy(args.host,model['name']) as proxy:
                    cmd=command(args.executable,model,suite,proxy.url,destination,args.limit)
                    entry['command']=cmd
                    with (destination/'evalscope.log').open('w') as log:
                        result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=3600)
                    entry.update(exit_code=result.returncode,requests=proxy.events,violations=proxy.violations,reports=report_files(destination))
                    entry['valid_isolation']=not proxy.violations and bool(proxy.events) and all(event['verified'] for event in proxy.events)
                    entry['summary']=summarize(entry)
                    entry['status']='completed' if result.returncode==0 and entry['valid_isolation'] and entry['summary'] and all(x['complete'] for x in entry['summary']) and all(event.get('status')==200 for event in proxy.events) else 'failed'
            except (OSError,RuntimeError,subprocess.SubprocessError) as error:entry.update(status='failed',error=str(error))
            finally:entry['isolation_cleanup']=isolation.stop_others(m.api,args.host)
            plan['runs'].append(entry);m.save(manifest,plan)
            print('  '+entry['status']+f" · {len(entry.get('requests',[]))} requests",flush=True)
            if entry['status']!='completed':failure=True
            if entry.get('violations'):raise RuntimeError('Isolation could not be verified; benchmark aborted')
    finally:
        isolation.stop_others(m.api,args.host);m.save(manifest,plan)
    print('Results: '+str(manifest))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
