#!/usr/bin/env python3
"""Loopback-only, authenticated benchmark launcher and progress service."""
import argparse,copy,hmac,json,os,secrets,shutil,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import modelprune as m

ROOT=Path(__file__).resolve().parent

def planned(job,limit):
    if job.get('status')=='completed':return job['sample_count']
    if job['type']=='standard':return limit
    if job.get('image'):return 3
    names=set(job['datasets']);model=job['record']
    return sum('modelprune_'+('coding' if task.get('category') in ('code-tracing','code-debugging') else task.get('skill') or 'core') in names and m.applicable(model,task) for task in m.suite())

def partial_reviews(folder):
    count=0
    for file in Path(folder).glob('reviews/*/*.jsonl'):
        try:
            for line in file.read_text().splitlines():
                try:json.loads(line);count+=1
                except ValueError:pass
        except OSError:pass
    return count

class Manager:
    def __init__(self,config):
        self.config=config
        if config.get('nltk_data'):os.environ['NLTK_DATA']=config['nltk_data']
        self.lock=threading.RLock();self.state={'state':'idle'};self.output=None;self.process=None
    def snapshot(self):
        with self.lock:
            state=dict(self.state)
            if state['state']=='running' and self.output and state.get('kind')!='discovery':
                try:
                    progress_file=self.output/'partial-run.json' if state.get('kind')=='partial' and (self.output/'partial-run.json').exists() else self.output/'run.json'
                    data=json.loads(progress_file.read_text());jobs=data['jobs'];done=[j for j in jobs if j['status']=='completed']
                    current=next((j for j in jobs if j['status'] in ('running','failed')),None)
                    if current is None:current=next((j for j in jobs if j['status']=='pending'),None)
                    completed=sum(j.get('sample_count',0) for j in done)
                    if current:completed+=partial_reviews(current['folder'])
                    state.update(total_samples=sum(planned(j,data['standard_limit']) for j in jobs),completed_samples=completed,total_jobs=len(jobs),completed_jobs=len(done),
                      current=(current['model']+' · '+current.get('suite','skill suites')) if current else 'Publishing results…')
                except (OSError,ValueError,KeyError):pass
            return state
    def start(self,kind='benchmark'):
        with self.lock:
            if self.state['state']=='running':return False,self.snapshot()
            ident=time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
            self.output=ROOT/'runs'/('report-'+ident)
            self.state={'state':'running','kind':kind,'id':ident,'total_samples':0,'completed_samples':0,'total_jobs':0,'completed_jobs':0,'current':'Discovering installed models…'}
            threading.Thread(target=self._discover if kind=='discovery' else self._partial if kind=='partial' else self._run,daemon=True).start()
            return True,self.snapshot()
    def _run(self):
        output=self.output;config=self.config
        try:
            cmd=[sys.executable,str(ROOT/'modelprune.py'),'run','--output',str(output),'--standard-limit',str(config.get('standard_limit',5))]
            for key in ['host','asr_python','asr_model','comfyui','comfy_python','comfy_model_paths','image_model_dir','evalscope_python','context','tokens','thinking_tokens']:
                if config.get(key) is not None:cmd += ['--'+key.replace('_','-'),str(config[key])]
            log=ROOT/'runs'/('report-service-'+self.state['id']+'.log');log.parent.mkdir(exist_ok=True)
            with log.open('w') as stream:
                self.process=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
                code=self.process.wait()
            if code:
                data=json.loads((output/'run.json').read_text()) if (output/'run.json').exists() else {}
                failed=next((j for j in data.get('jobs',[]) if j['status']=='failed'),{})
                import isolation
                fallback=failed.get('error') or 'Benchmark process exited '+str(code)+'. See '+str(log)
                raise RuntimeError(isolation.failure_reason(failed.get('folder',output),fallback))
            self.publish(output)
            with self.lock:
                self.state.update(self.snapshot(),state='completed',current='Complete')
                self.state['completed_samples']=self.state.get('total_samples',0);self.state['completed_jobs']=self.state.get('total_jobs',0)
        except Exception as error:
            with self.lock:self.state.update(state='failed',error=str(error))
        finally:self.process=None
    def _partial(self):
        import incremental,evalscope_run
        output=self.output
        try:
            baseline=json.loads((Path(self.config['publish_dir'])/'ModelPrune-EvalScope-results.json').read_text())
            if baseline.get('fixture_hash') and baseline['fixture_hash']!=evalscope_run.fixture_hash():raise RuntimeError('Benchmark fixtures changed; run a full benchmark instead')
            names=incremental.select_models(baseline,m.inventory(self.config.get('host','http://127.0.0.1:11434')))
            images=incremental.select_images(baseline,self.config.get('comfyui'),self.config.get('image_model_dir'))
            if not names and not images:
                with self.lock:self.state.update(state='completed',current='No new models',message='No new or changed models need benchmarking.')
                return
            python=self.config.get('evalscope_python') or str(Path(shutil.which('evalscope') or '/missing').resolve().parent/'python')
            version=subprocess.check_output([python,'-c','from importlib.metadata import version;print("EvalScope "+version("evalscope"))'],text=True).strip()
            if version!=baseline['engine']:raise RuntimeError('EvalScope version changed; run a full benchmark instead')
            cmd=[sys.executable,str(ROOT/'modelprune.py'),'run','--output',str(output),'--standard-limit',str(baseline['standard_limit'])]
            if names:cmd+=['--models']+names
            else:cmd+=['--images-only']
            if images:cmd+=['--image-models']+images
            options={**self.config,**{key:baseline['config'].get(key) for key in ['context','tokens','thinking_tokens']}}
            for key in ['host','asr_python','asr_model','evalscope_python','context','tokens','thinking_tokens']+(['comfyui','comfy_python','comfy_model_paths','image_model_dir'] if images else []):
                if options.get(key) is not None:cmd+=['--'+key.replace('_','-'),str(options[key])]
            log=ROOT/'runs'/('partial-'+self.state['id']+'.log');log.parent.mkdir(exist_ok=True)
            with log.open('w') as stream:
                self.process=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT);code=self.process.wait()
            if code:raise RuntimeError('Partial benchmark failed; see '+str(log))
            fresh=json.loads((output/'run.json').read_text());merged=incremental.merge(baseline,fresh)
            # Retain a separate fresh-run checkpoint for this operation's progress.
            m.save(output/'partial-run.json',fresh);m.save(output/'run.json',merged)
            self.publish(output)
            with self.lock:self.state.update(self.snapshot(),state='completed',current='Partial benchmark complete',message='New model scores added. Existing scores preserved.')
        except Exception as error:
            with self.lock:self.state.update(state='failed',error=str(error))
        finally:self.process=None
    def _discover(self):
        output=self.output
        try:
            output.mkdir(parents=True)
            with self.lock:self.state['current']='Scanning installed model stores…'
            cmd=[sys.executable,str(ROOT/'modelprune.py'),'--host',self.config.get('host','http://127.0.0.1:11434'),'list','--output',str(output/'inventory.json')]
            with (output/'discovery.log').open('w') as log:
                self.process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
                code=self.process.wait()
            if code:raise RuntimeError('Discovery failed; see '+str(output/'discovery.log'))
            data=json.loads((Path(self.config['publish_dir'])/'ModelPrune-EvalScope-results.json').read_text())
            data['discovery']=json.loads((output/'inventory.json').read_text())
            import model_aliases
            model_aliases.enrich_history(data,data['discovery'])
            data['discovery_updated']=time.strftime('%Y-%m-%dT%H:%M:%S%z')
            m.save(output/'run.json',data)
            self.publish(output)
            with self.lock:self.state.update(state='completed',current='Discovery complete',models_found=len(data['discovery']['models']))
        except Exception as error:
            with self.lock:self.state.update(state='failed',error=str(error))
        finally:self.process=None
    def publish(self,output):
        data=json.loads((output/'run.json').read_text())
        if (not data.get('jobs') and data.get('results')) or any(j['status']!='completed' for j in data['jobs']):raise RuntimeError('Refusing incomplete benchmark report')
        m.report(data,output)
        destination=Path(self.config['publish_dir']);destination.mkdir(parents=True,exist_ok=True)
        for source,target in [('report.html','ModelPrune-report.html'),('comparison.csv','ModelPrune-comparison.csv'),('discovery.json','ModelPrune-inventory.json'),('run.json','ModelPrune-EvalScope-results.json')]:
            temp=destination/(target+'.tmp');shutil.copy2(output/source,temp);temp.replace(destination/target)

def server(config,manager=None):
    manager=manager or Manager(config);token=config['token'];port=config['port']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def origin_ok(self):
            return self.headers.get('Host') in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)) and self.headers.get('Origin') in (None,'null','http://127.0.0.1:'+str(self.server.server_port),'http://localhost:'+str(self.server.server_port))
        def send_json(self,code,data):
            self.send_response(code)
            if self.origin_ok():
                origin=self.headers.get('Origin')
                if origin:self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin');self.send_header('Access-Control-Allow-Private-Network','true')
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(json.dumps(data).encode())
        def authorized(self):
            return self.origin_ok() and hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)
        def do_OPTIONS(self):
            if not self.origin_ok():return self.send_json(403,{'error':'Origin rejected'})
            self.send_response(204);self.send_header('Access-Control-Allow-Origin',self.headers.get('Origin','null'));self.send_header('Access-Control-Allow-Methods','GET, POST');self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type');self.send_header('Access-Control-Allow-Private-Network','true');self.end_headers()
        def do_GET(self):
            if not self.authorized():return self.send_json(403,{'error':'Unauthorized report control'})
            if self.path!='/api/status':return self.send_json(404,{'error':'Not found'})
            self.send_json(200,manager.snapshot())
        def do_POST(self):
            if not self.authorized():return self.send_json(403,{'error':'Unauthorized report control'})
            if self.path not in ('/api/run','/api/discover','/api/partial'):return self.send_json(404,{'error':'Not found'})
            length=int(self.headers.get('Content-Length',0))
            if length>100:return self.send_json(400,{'error':'Run options cannot be supplied by the page'})
            try:body=json.loads(self.rfile.read(length) or '{}')
            except ValueError:return self.send_json(400,{'error':'Invalid request'})
            if body!={}:return self.send_json(400,{'error':'Run options cannot be supplied by the page'})
            started,state=manager.start('discovery') if self.path=='/api/discover' else manager.start('partial') if self.path=='/api/partial' else manager.start();self.send_json(202 if started else 409,state if started else {'error':'A benchmark or discovery is already running',**state})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.config.read_text())
    if len(config.get('token',''))<32:raise SystemExit('Missing strong report-control token')
    server(config).serve_forever()
