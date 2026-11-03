"""Unified ModelPrune run: every inference and grade is scheduled by EvalScope."""
import argparse,copy,json,os,shutil,subprocess,time,statistics,hashlib
from pathlib import Path
import modelprune as m,discovery,isolation,evalscope_bridge as bridge
import model_aliases

ROOT=Path(__file__).resolve().parent

def fixture_hash():
    return hashlib.sha256(json.dumps(m.suite(),sort_keys=True).encode()+(ROOT/'evalscope_native.py').read_bytes()+(ROOT/'image_benchmark.py').read_bytes()).hexdigest()

def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def import_custom(folder,model,image=False):
    tasks={t['id']:copy.deepcopy(t) for t in m.suite()};results=[]
    if image:
        import image_benchmark
        tasks={t['id']:dict(t,kind='image-generation',category='image-generation',skill='image-generation') for t in image_benchmark.TASKS}
    for path in sorted(Path(folder).glob('reviews/*/*.jsonl')):
        for row in read_lines(path):
            score=row['sample_score']['score'];result=json.loads(score['prediction'])
            if not result.get('isolation',{}).get('verified'):raise RuntimeError('Unverified EvalScope custom sample')
            task=tasks[result['task']]
            value=score['value'].get('acc')
            if value not in (0,1):raise RuntimeError('Missing binary EvalScope custom metric')
            result.update(points=value*task['level'],repeat=row['sample_score'].get('generation_index',0),score_engine='EvalScope',evalscope_review=str(path),evalscope_metric='acc')
            if score.get('metadata',{}).get('image_metrics'):result['metrics']=score['metadata']['image_metrics']
            results.append(result)
    return tasks,results

def import_standard(folder,entry):
    reports=bridge.summarize(entry)
    if len(reports)!=1 or not reports[0]['complete']:raise RuntimeError('Incomplete standard EvalScope report')
    tasks={};results=[]
    for path in sorted(Path(folder).glob('reviews/*/*.jsonl')):
        predictions=Path(folder)/'predictions'/path.relative_to(Path(folder)/'reviews')
        raw={r['index']:r for r in read_lines(predictions)}
        for row in read_lines(path):
            sample=row['sample_score'];score=sample['score'];key=score.get('main_score_name');value=score.get('value',{}).get(key)
            if value not in (0,1):raise RuntimeError('Standard primary sample score is not binary: '+str(key))
            index=row['index'];record=raw[index];output=record['model_output'];task_id=entry['suite']+'-'+str(index)
            task=dict(id=task_id,level=1,category='standard-'+entry['suite'],kind='decision' if entry['suite']=='boolq' else 'generation',
                      prompt='\n'.join(str(msg.get('content','')) for msg in record['messages']),expected=row.get('target'),benchmark=entry['suite'])
            if entry['suite']!='boolq':task['skill']='completion'
            tasks[task_id]=task
            events=entry['requests'];verified=entry['valid_isolation'] and all(e['verified'] for e in events)
            result=dict(model=entry['model'],task=task_id,level=1,category=task['category'],kind=task['kind'],points=value,repeat=0,
                        seconds=output.get('time') or statistics.median(e['seconds'] for e in events),answer=score.get('extracted_prediction'),
                        response=output,score_engine='EvalScope',evalscope_review=str(path),evalscope_metric=key,isolation={'verified':verified,'source':'EvalScope isolation proxy'})
            if output.get('error'):result['error']=str(output['error'])
            results.append(result)
    if len(results)!=reports[0]['samples']:raise RuntimeError('Review count does not match EvalScope report')
    return tasks,results

def project(data):
    taskmap={};results=[];image_results=[];image_tasks=[];engine_reports=[]
    for job in data['jobs']:
        if job['status']!='completed':continue
        folder=Path(job['folder'])
        if job['type']=='custom':
            tasks,items=import_custom(folder,job['model'],job.get('image',False))
            if job.get('image'):
                image_tasks=list(tasks.values());image_results.extend(items)
            else:
                for item in items:
                    task=tasks[item['task']]
                    if task.get('category') in ('code-tracing','code-debugging'):task['skill']='coding'
                    taskmap[task['id']]=task
                results.extend(items)
        else:
            tasks,items=import_standard(folder,job['entry']);taskmap.update(tasks);results.extend(items)
        engine_reports.extend({'model':job['model'],'suite':r['data'].get('dataset_name'),'source':str(folder/r['path']),'data':r['data']} for r in bridge.report_files(folder))
    data['tasks']=list(taskmap.values());data['results']=results;data['engine_reports']=engine_reports
    for model in data['models']:
        if 'completion' in model['capabilities'] and 'coding' not in model['capabilities']:model['capabilities'].append('coding')
    if image_results:data['image_benchmark']={'tasks':image_tasks,'results':image_results,'method':'EvalScope native image-generation suite: coarse color/background/layout checks, not aesthetic quality. 768x768, Euler, 20 steps, CFG 7, seed 42.'}
    return data

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default=os.environ.get('OLLAMA_HOST','http://127.0.0.1:11434'))
    p.add_argument('--models',nargs='+');p.add_argument('--output',type=Path)
    p.add_argument('--resume',type=Path)
    p.add_argument('--images-only',action='store_true')
    p.add_argument('--image-models',nargs='+')
    p.add_argument('--standard-limit',type=int,default=25);p.add_argument('--repeats',type=int,default=1,choices=[1])
    p.add_argument('--asr-python');p.add_argument('--asr-model');p.add_argument('--comfyui',type=Path);p.add_argument('--comfy-python')
    p.add_argument('--comfy-model-paths',type=Path);p.add_argument('--image-model-dir',type=Path)
    p.add_argument('--evalscope-python',default=str(Path(shutil.which('evalscope') or '/missing').resolve().parent/'python'))
    p.add_argument('--context',type=int,default=4096);p.add_argument('--tokens',type=int,default=256);p.add_argument('--thinking-tokens',type=int,default=2048)
    p.add_argument('--scan-path',action='append',type=Path);p.add_argument('--scan-limit',type=int,default=5_000_000)
    args=p.parse_args(argv)
    previous=None
    if args.resume:
        previous=json.loads(args.resume.read_text())
        if not previous.get('engine'):
            p.error('Benchmark protocol changed: legacy runs cannot resume into the EvalScope engine; start a fresh run')
        if previous.get('version')!='7.0.0' or not previous.get('jobs'):p.error('Benchmark protocol changed: a unified EvalScope run is required')
        if previous.get('fixture_hash') and previous['fixture_hash']!=fixture_hash():p.error('EvalScope fixture or rubric changed; start a fresh run')
        args.output=args.resume.resolve().parent;args.host=previous['host'];args.standard_limit=previous['standard_limit']
        args.models=[model['name'] for model in previous['models']]
        for key in ['asr_python','asr_model','context','tokens','thinking_tokens']:setattr(args,key,previous['config'].get(key))
        for key,value in previous.get('runtime_options',{}).items():
            if value is not None:setattr(args,key,Path(value) if key in ('comfyui','comfy_model_paths','image_model_dir') else value)
    if args.output is None:args.output=ROOT/'runs'/time.strftime('evalscope-%Y%m%d-%H%M%S')
    if args.standard_limit<1:p.error('--standard-limit must be positive')
    if args.output.exists() and not previous:p.error('Choose a fresh --output directory')
    models=model_aliases.group_models(m.inventory(args.host))
    found=previous['discovery'] if previous else discovery.scan(models,(args.scan_path or [])+discovery.default_roots(),args.scan_limit)
    if args.models:
        args.models=model_aliases.resolve_requested(models,args.models)
        missing=set(args.models)-{x['name'] for x in models}
        if missing:
            external={item['name'] for item in found['models'] if item.get('source')!='Ollama'}&missing
            if external:p.error('Found outside Ollama, but no benchmark/isolation adapter is selected: '+', '.join(sorted(external)))
            p.error('Unknown models: '+', '.join(sorted(missing)))
        models=[x for x in models if x['name'] in args.models]
    models=[x for x in models if set(x['capabilities'])&{'completion','decision','speech'}]
    if args.images_only:models=[]
    if not models and not (args.images_only and args.comfyui):p.error('No eligible Ollama models')
    if any('speech' in x['capabilities'] for x in models) and not(args.asr_python and args.asr_model):p.error('Speech models require --asr-python and --asr-model')
    version=subprocess.check_output([args.evalscope_python,'-c','import evalscope;from importlib.metadata import version;print(version("evalscope"))'],text=True).strip()
    if previous:
        current={model['name']:model.get('digest') for model in models}
        if any(current.get(model['name'])!=model.get('digest') for model in previous['models']):p.error('Model digest changed; start a fresh run')
        if previous['engine']!='EvalScope '+version:p.error('EvalScope version changed; start a fresh run')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=bool(previous))
    config=dict(repeats=1,seed=42,context=args.context,tokens=args.tokens,thinking_tokens=args.thinking_tokens,thinking='off',timeout=180,asr_python=args.asr_python,asr_model=args.asr_model)
    if previous:
        data=previous;config=data['config']
    else:
        data=dict(version='7.0.0',engine='EvalScope '+version,protocol='chat-isolated-v3',created=time.strftime('%Y-%m-%dT%H:%M:%S%z'),host=args.host,
          ollama_version=m.api(args.host,'/api/version').get('version'),hardware=m.hardware(),config=config,models=copy.deepcopy(models),jobs=[],tasks=[],results=[],
          discovery=found,
          standard_limit=args.standard_limit,evaluation_notes='All scores imported from native EvalScope reviews; limited standard samples and small custom skill fixtures. Overlap is specific to these workloads.')
        for index,model in enumerate(sorted(models,key=lambda x:x['size'])):
            datasets=['modelprune_core'] if set(model['capabilities'])&{'completion','decision'} else []
            if 'completion' in model['capabilities']:datasets.append('modelprune_coding')
            datasets += ['modelprune_'+cap for cap in ['vision','audio','speech','tools','thinking'] if cap in model['capabilities']]
            data['jobs'].append(dict(model=model['name'],type='custom',datasets=datasets,status='pending',folder=str(args.output/f'{index:02d}-skills'),record=model))
            for suite in bridge.SUITES:
                if bridge.applicable(model,suite):data['jobs'].append(dict(model=model['name'],type='standard',suite=suite,status='pending',folder=str(args.output/f'{index:02d}-{suite}'),record=model))
        if args.comfyui:
            if not args.comfy_python:p.error('--comfyui requires --comfy-python')
            for checkpoint in sorted((args.image_model_dir or args.comfyui/'models/checkpoints').glob('*.safetensors')):
                if args.image_models and checkpoint.name not in args.image_models:continue
                data['jobs'].append(dict(model=checkpoint.name,type='custom',image=True,datasets=['modelprune_image_generation'],status='pending',folder=str(args.output/f'image-{checkpoint.stem}'),record={'name':checkpoint.name,'capabilities':['image-generation'],'weight_signature':[checkpoint.stat().st_size,checkpoint.stat().st_mtime_ns]}))
    data['fixture_hash']=fixture_hash()
    data['runtime_options']={'comfyui':str(args.comfyui) if args.comfyui else None,'comfy_python':args.comfy_python,'evalscope_python':args.evalscope_python,'comfy_model_paths':str(args.comfy_model_paths) if args.comfy_model_paths else None,'image_model_dir':str(args.image_model_dir) if args.image_model_dir else None}
    manifest=args.output/'run.json';m.save(manifest,data)
    for job in data['jobs']:
        if job['status']=='completed':continue
        job['status']='running';m.save(manifest,data)
        print('EvalScope '+job['model']+' · '+job.get('suite','all skill suites'),flush=True)
        folder=Path(job['folder'])
        if folder.exists():
            archived=folder.with_name(folder.name+'-excluded-'+str(time.time_ns()))
            folder.rename(archived);job.setdefault('excluded_attempts',[]).append(str(archived))
        folder.mkdir()
        try:
            if job['type']=='custom':
                worker=dict(model_record=job['record'],host=args.host,datasets=job['datasets'],work_dir=str(folder),transport_config=config,image=job.get('image',False),
                            comfyui=str(args.comfyui) if args.comfyui else None,comfy_python=args.comfy_python,comfy_model_paths=str(args.comfy_model_paths) if args.comfy_model_paths else None,image_host='http://127.0.0.1:8190')
                m.save(folder/'worker-config.json',worker)
                cmd=[args.evalscope_python,str(ROOT/'evalscope_worker.py'),str(folder/'worker-config.json')]
                with (folder/'worker.log').open('w') as log:code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=3600).returncode
                if code:raise RuntimeError(isolation.failure_reason(folder,'EvalScope skill worker failed; see '+str(folder/'worker.log')))
                expected=sum(len(__import__('image_benchmark').TASKS) if name=='modelprune_image_generation' else sum(1 for task in m.suite() if ('coding' if task.get('category') in ('code-tracing','code-debugging') else task.get('skill') or 'core')==name.removeprefix('modelprune_') and m.applicable(job['record'],task)) for name in job['datasets'])
                _,items=import_custom(folder,job['model'],job.get('image',False))
                if len(items)!=expected:raise RuntimeError('EvalScope skill coverage incomplete')
                job['sample_count']=len(items)
            else:
                isolation.stop_others(m.api,args.host)
                with bridge.Proxy(args.host,job['model']) as proxy:
                    cmd=bridge.command('evalscope',job['record'],job['suite'],proxy.url,folder,args.standard_limit)
                    cmd=[args.evalscope_python,str(ROOT/'evalscope_cli_worker.py')]+cmd[1:]
                    with (folder/'worker.log').open('w') as log:code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=3600).returncode
                entry=dict(model=job['model'],suite=job['suite'],requests=proxy.events,valid_isolation=not proxy.violations and bool(proxy.events) and all(e['verified'] and e.get('status')==200 for e in proxy.events),reports=bridge.report_files(folder))
                job['entry']=entry
                if code or not entry['valid_isolation']:raise RuntimeError('Standard EvalScope task failed')
                _,items=import_standard(folder,entry);job['sample_count']=len(items)
            job['status']='completed';print('  completed · '+str(job['sample_count'])+' samples',flush=True)
        except BaseException as error:
            job.update(status='failed',error=str(error));m.save(manifest,data);raise
        finally:isolation.stop_others(m.api,args.host)
        m.save(manifest,data)
    project(data);m.save(manifest,data);m.report(data,args.output)

if __name__=='__main__':main()
